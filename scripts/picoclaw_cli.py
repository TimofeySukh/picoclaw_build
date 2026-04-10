#!/usr/bin/env python3

from __future__ import annotations

import curses
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import textwrap
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from http.cookiejar import CookieJar


ROOT = "/Users/Tim/Documents/picoclaw"
CONTAINER_NAME = "picoclaw"
LAUNCHER_BASE = "http://127.0.0.1:18800"
TOKEN_RE = re.compile(r"Dashboard token(?: \(this run\))?:\s+(\S+)")
ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
DOCKER_ENV = {
    **os.environ,
    **({} if os.environ.get("DOCKER_HOST") else {"DOCKER_CONTEXT": "default"}),
}
POLL_SECONDS = 0.4
MAX_SCROLLBACK = 2500
IGNORED_OUTPUT_LINES = {
    "",
    "TZ environment: UTC",
    "ZONEINFO environment:",
    "Time zone loaded successfully: UTC",
    "Warning: deny patterns are disabled. All commands will be allowed.",
}


def current_dashboard_token() -> str:
    completed = subprocess.run(
        ["docker", "logs", "--tail", "80", CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=True,
        env=DOCKER_ENV,
    )
    matches = TOKEN_RE.findall(completed.stdout + completed.stderr)
    if not matches:
        raise RuntimeError("Launcher token not found in docker logs.")
    return matches[-1]


class LauncherClient:
    def __init__(self) -> None:
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._logged_in = False

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        if not self._logged_in:
            self.login()

        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            urllib.parse.urljoin(LAUNCHER_BASE, path),
            data=body,
            headers=headers,
            method=method,
        )
        with self._opener.open(req, timeout=5) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def login(self) -> None:
        token = current_dashboard_token()
        req = urllib.request.Request(
            urllib.parse.urljoin(LAUNCHER_BASE, "/api/auth/login"),
            data=json.dumps({"token": token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener.open(req, timeout=5):
            pass
        self._logged_in = True

    def pending(self) -> list[dict]:
        data = self._request("/api/host-exec/requests")
        return [item for item in data.get("requests", []) if item.get("status") == "pending"]

    def decide(self, request_id: str, action: str) -> dict:
        return self._request(
            f"/api/host-exec/requests/{urllib.parse.quote(request_id)}/{action}",
            method="POST",
            payload={"decided_by": "picoclaw-tui"},
        )


def sanitize_output(chunk: bytes) -> str:
    text = chunk.decode("utf-8", errors="ignore")
    text = text.replace("\x1b[6n", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ANSI_RE.sub("", text)
    text = text.replace("\b", "")
    return text


def should_hide_line(line: str) -> bool:
    stripped = line.strip()
    if stripped in IGNORED_OUTPUT_LINES:
        return True
    if stripped in {"<tool_call>", "</tool_call>"}:
        return True
    if stripped.startswith("<function=") or stripped.startswith("</function>"):
        return True
    if stripped.startswith("<parameter=") or stripped.startswith("</parameter>"):
        return True
    return False


def is_banner_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "Interactive mode" in stripped:
        return True
    banner_chars = "█╗╔╝═║"
    return any(ch in stripped for ch in banner_chars)


def spawn_agent() -> int:
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(
            "docker",
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "TERM=dumb",
                CONTAINER_NAME,
                "sh",
                "-lc",
                "exec picoclaw agent",
            ],
            DOCKER_ENV,
        )
    return fd


@dataclass
class PopupState:
    selected_request: int = 0
    selected_action: int = 0


class PicoClawTUI:
    def __init__(self, stdscr) -> None:
        self.stdscr = stdscr
        self.client = LauncherClient()
        self.child_fd = spawn_agent()
        self.output_lines: deque[str] = deque(maxlen=MAX_SCROLLBACK)
        self.partial_line = ""
        self.input_buffer = ""
        self.status = "Connected"
        self.last_poll = 0.0
        self.pending_requests: list[dict] = []
        self.pending_popup_open = False
        self.pending_popup = PopupState()
        self.last_pending_ids: tuple[str, ...] = ()
        self.scroll_offset = 0
        self.should_exit = False
        self.dirty = True
        self.init_screen()

    def init_screen(self) -> None:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)
        self.stdscr.nodelay(True)
        self.colors_enabled = False
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
            self.colors_enabled = True
        except curses.error:
            self.colors_enabled = False
        self.add_output("[picoclaw] TUI ready. Type normally below. When approval is needed, use arrows and Enter.")

    def color(self, pair: int) -> int:
        if self.colors_enabled:
            return curses.color_pair(pair)
        return curses.A_NORMAL

    def add_output(self, text: str) -> None:
        for raw_line in text.split("\n"):
            line = raw_line.rstrip()
            if should_hide_line(line):
                continue
            self.output_lines.append(line)
        self.dirty = True

    def poll_child(self) -> None:
        try:
            readable, _, _ = select.select([self.child_fd], [], [], 0)
        except OSError:
            self.should_exit = True
            self.dirty = True
            return
        if self.child_fd not in readable:
            return
        try:
            chunk = os.read(self.child_fd, 4096)
        except OSError:
            self.should_exit = True
            self.dirty = True
            return
        if not chunk:
            self.should_exit = True
            self.dirty = True
            return
        text = sanitize_output(chunk)
        if not text:
            return
        combined = self.partial_line + text
        lines = combined.split("\n")
        self.partial_line = lines.pop() if combined and not combined.endswith("\n") else ""
        for line in lines:
            clean = line.rstrip()
            if should_hide_line(clean):
                continue
            self.output_lines.append(clean)
        self.dirty = True

    def poll_pending(self) -> None:
        now = time.monotonic()
        if now - self.last_poll < POLL_SECONDS:
            return
        self.last_poll = now
        try:
            pending = self.client.pending()
            self.status = "Connected"
        except Exception as exc:  # noqa: BLE001
            self.status = f"Approval API error: {exc}"
            self.dirty = True
            return
        pending_ids = tuple(item["id"] for item in pending)
        if pending_ids != self.last_pending_ids:
            self.last_pending_ids = pending_ids
            if pending_ids:
                self.pending_popup_open = True
                self.pending_popup.selected_request = min(self.pending_popup.selected_request, max(len(pending) - 1, 0))
                self.pending_popup.selected_action = 0
            self.dirty = True
        self.pending_requests = pending
        if not pending:
            if self.pending_popup_open:
                self.dirty = True
            self.pending_popup_open = False

    def send_line(self, line: str) -> None:
        os.write(self.child_fd, line.encode("utf-8") + b"\n")
        self.dirty = True

    def decide_pending(self, action: str) -> None:
        if not self.pending_requests:
            return
        request = self.pending_requests[self.pending_popup.selected_request]
        try:
            result = self.client.decide(request["id"], action)
            self.add_output(f"[approval] {action}d {result['id']}")
        except Exception as exc:  # noqa: BLE001
            self.add_output(f"[approval] failed to {action} {request['id']}: {exc}")
        self.pending_popup_open = False
        self.last_poll = 0.0
        self.poll_pending()
        self.dirty = True

    def wrap_line(self, line: str, width: int) -> list[str]:
        if width <= 1:
            return [line[:width]]
        return textwrap.wrap(line or " ", width=width, replace_whitespace=False, drop_whitespace=False) or [""]

    def build_message_blocks(self, width: int) -> list[list[str]]:
        lines = list(self.output_lines)
        if self.partial_line:
            lines.append(self.partial_line)

        messages: list[list[str]] = []
        banner_block: list[str] = []
        for line in lines:
            if not line.strip():
                if banner_block:
                    messages.append(banner_block)
                    banner_block = []
                continue
            if is_banner_line(line):
                banner_block.append(line)
                if "Interactive mode" in line:
                    messages.append(banner_block)
                    banner_block = []
                continue
            if banner_block:
                messages.append(banner_block)
                banner_block = []
            messages.append([line])
        if banner_block:
            messages.append(banner_block)

        content_width = max(10, width - 8)
        rendered: list[list[str]] = []
        for message in messages:
            block: list[str] = []
            border = "─" * content_width
            block.append(f"╭{border}╮")
            for raw in message:
                for wrapped in self.wrap_line(raw, content_width - 2):
                    block.append(f"│ {wrapped.ljust(content_width - 2)} │")
            block.append(f"╰{border}╯")
            rendered.append(block)
        return rendered

    def draw_output(self, top: int, height: int, width: int) -> None:
        rendered_lines: list[str] = []
        for idx, block in enumerate(self.build_message_blocks(width)):
            if idx > 0:
                rendered_lines.append("")
            rendered_lines.extend(block)

        visible = rendered_lines[-height - self.scroll_offset :]
        if self.scroll_offset:
            visible = visible[:height]
        else:
            visible = visible[-height:]
        start_row = top
        for idx, line in enumerate(visible[-height:]):
            attr = self.color(1) if line.startswith(("╭", "╰", "│")) else curses.A_NORMAL
            self.stdscr.addnstr(start_row + idx, 1, line, width - 2, attr)

    def draw_popup(self, height: int, width: int) -> None:
        if not self.pending_popup_open or not self.pending_requests:
            return
        box_w = max(70, min(width - 6, 110))
        box_h = min(12, height - 4)
        y = max(2, (height - box_h) // 2)
        x = max(2, (width - box_w) // 2)
        win = curses.newwin(box_h, box_w, y, x)
        win.keypad(True)
        win.border()
        win.addnstr(0, 2, " Approval Required ", box_w - 4, self.color(2) | curses.A_BOLD)

        request = self.pending_requests[self.pending_popup.selected_request]
        details = [
            f"Request {self.pending_popup.selected_request + 1}/{len(self.pending_requests)}",
            f"Target: {request.get('target') or 'host'}",
            f"Reason: {request.get('reason') or '-'}",
            "Command:",
        ]
        row = 1
        for detail in details:
            for line in self.wrap_line(detail, box_w - 4):
                if row >= box_h - 4:
                    break
                win.addnstr(row, 2, line, box_w - 4)
                row += 1
        for line in self.wrap_line(request.get("command") or "", box_w - 6):
            if row >= box_h - 3:
                break
            win.addnstr(row, 4, line, box_w - 6, self.color(1))
            row += 1

        actions = ["Approve", "Deny", "Later"]
        col = 2
        button_row = box_h - 2
        for idx, action in enumerate(actions):
            label = f" {action} "
            attr = curses.A_REVERSE if idx == self.pending_popup.selected_action else curses.A_NORMAL
            if action == "Approve":
                attr |= self.color(3)
            elif action == "Deny":
                attr |= self.color(4)
            else:
                attr |= self.color(2)
            win.addnstr(button_row, col, label, len(label), attr)
            col += len(label) + 2
        win.refresh()

    def render(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        title = " PicoClaw TUI "
        status = f"{self.status} | approvals: {len(self.pending_requests)}"
        self.stdscr.addnstr(0, 0, title, width - 1, self.color(1) | curses.A_BOLD)
        if len(status) < width - len(title) - 2:
            self.stdscr.addnstr(0, width - len(status) - 1, status, len(status), self.color(2))

        output_header_row = 1
        output_top = 2
        output_height = max(4, height - 5)
        self.stdscr.addnstr(output_header_row, 1, "Messages", width - 2, self.color(2) | curses.A_BOLD)
        self.draw_output(output_top, output_height, width)

        input_row = height - 2
        footer_row = height - 1
        self.stdscr.hline(input_row - 1, 0, curses.ACS_HLINE, width)
        prompt = "You > "
        self.stdscr.addnstr(input_row, 0, prompt + self.input_buffer, width - 1)
        footer = "Enter: send | Ctrl+C: exit | When popup opens: arrows + Enter"
        self.stdscr.addnstr(footer_row, 0, footer, width - 1, self.color(2))

        cursor_x = min(len(prompt) + len(self.input_buffer), width - 1)
        self.stdscr.move(input_row, cursor_x)
        self.stdscr.refresh()
        self.draw_popup(height, width)
        self.dirty = False

    def handle_popup_key(self, key: int) -> None:
        if key in (curses.KEY_UP, ord("k")) and self.pending_requests:
            self.pending_popup.selected_request = (self.pending_popup.selected_request - 1) % len(self.pending_requests)
            self.dirty = True
            return
        if key in (curses.KEY_DOWN, ord("j")) and self.pending_requests:
            self.pending_popup.selected_request = (self.pending_popup.selected_request + 1) % len(self.pending_requests)
            self.dirty = True
            return
        if key in (curses.KEY_LEFT, ord("h")):
            self.pending_popup.selected_action = (self.pending_popup.selected_action - 1) % 3
            self.dirty = True
            return
        if key in (curses.KEY_RIGHT, ord("l"), 9):
            self.pending_popup.selected_action = (self.pending_popup.selected_action + 1) % 3
            self.dirty = True
            return
        if key in (27,):
            self.pending_popup_open = False
            self.dirty = True
            return
        if key in (10, 13, curses.KEY_ENTER):
            action = ["approve", "deny", "later"][self.pending_popup.selected_action]
            if action == "later":
                self.pending_popup_open = False
                return
            self.decide_pending(action)

    def handle_input_key(self, key: int) -> None:
        if key in (3,):
            self.should_exit = True
            self.dirty = True
            return
        if key in (10, 13, curses.KEY_ENTER):
            line = self.input_buffer.strip()
            if line:
                self.send_line(line)
            self.input_buffer = ""
            self.dirty = True
            return
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.input_buffer = self.input_buffer[:-1]
            self.dirty = True
            return
        if key == curses.KEY_PPAGE:
            self.scroll_offset = min(self.scroll_offset + 5, max(len(self.output_lines) - 1, 0))
            self.dirty = True
            return
        if key == curses.KEY_NPAGE:
            self.scroll_offset = max(self.scroll_offset - 5, 0)
            self.dirty = True
            return
        if key == curses.KEY_RESIZE:
            self.dirty = True
            return
        if 32 <= key <= 126:
            self.input_buffer += chr(key)
            self.dirty = True

    def run(self) -> int:
        while not self.should_exit:
            self.poll_child()
            self.poll_pending()
            if self.dirty:
                self.render()
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                self.should_exit = True
                break
            if key == -1:
                time.sleep(0.02)
                continue
            if self.pending_popup_open:
                self.handle_popup_key(key)
            else:
                self.handle_input_key(key)
        return 0


def main(stdscr) -> int:
    app = PicoClawTUI(stdscr)
    return app.run()


if __name__ == "__main__":
    try:
        raise SystemExit(curses.wrapper(main))
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"[picoclaw] {exc}", file=sys.stderr)
        raise SystemExit(1)
