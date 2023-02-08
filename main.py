from enum import Enum
from pprint import pprint
import re
import socket
import ssl
from typing import Tuple, Optional
from urllib.parse import urlparse
import tkinter


def request(rawUrl):
    # TODO: automatically prepend http
    url = urlparse(rawUrl)

    s = socket.socket(
        family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    assert url.scheme in ["http", "https"], f"Unknown scheme {url.scheme}"

    if url.scheme == "https":
        ctx = ssl.create_default_context()
        s = ctx.wrap_socket(s, server_hostname=url.netloc)

    # TODO: use url.port if it exists
    port = url.port or (80 if url.scheme == "http" else 443)

    assert url.hostname
    s.connect((url.hostname, port))
    req = (
        f"GET /{url.path} HTTP/1.1\r\n"
        + f"Host: {url.netloc}\r\n"
        + "Connection: close\r\n"
        + "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36\r\n"
        + "\r\n"
    )
    # TODO: if not everything was sent, we gotta send the remainder
    s.send(req.encode("utf8"))

    response = s.makefile("r", encoding="utf8", newline="\r\n")

    statusline = response.readline()
    _, status, explanation = statusline.split(" ", 2)
    assert status == "200", f"{status}: {explanation}"

    headers = {}
    while True:
        line = response.readline()
        if line == "\r\n":
            break
        header, value = line.split(":", 1)
        headers[header.lower()] = value.strip()

    assert "transfer-encoding" not in headers
    assert "content-encoding" not in headers

    body = response.read()
    s.close()
    return headers, body


def hawp(input, expr) -> Tuple[Optional[str], str]:
    x = re.match(expr, input, flags=re.DOTALL)
    if x is None:
        return None, input
    start, end = x.span()
    return input[start:end], input[end:]


def lex(body):
    ParserState = Enum("ParserState", ["ANYTHING", "TAGNAME"])
    state = ParserState.ANYTHING
    in_body = False
    text = ""

    while body:
        if state == ParserState.ANYTHING:
            match, body = hawp(body, "<|\n+|[^<\n]+")
            assert match
            if match == "<":
                state = ParserState.TAGNAME
            elif match.startswith("\n"):
                if in_body and not text.endswith("\n"):
                    text += "\n"
            elif match:
                state = ParserState.ANYTHING
                if in_body:
                    text += match
            pass
        elif state == ParserState.TAGNAME:
            # TODO: deal with > inside tags
            tag, body = hawp(body, "/?[a-zA-Z!-]+")
            assert tag
            tag = tag.lower()
            _, body = hawp(body, ".*?>")
            if tag == "body":
                in_body = True
            elif tag == "/body":
                in_body = False
            state = ParserState.ANYTHING
        else:
            assert False, f"Bad parser state: {state}"
    return text


HSTEP, VSTEP = 13, 18


def layout(text):
    display_list = []
    cursor_x, cursor_y = HSTEP, VSTEP
    for c in text:
        display_list.append((cursor_x, cursor_y, c))
        if c == "\n":
            cursor_y += VSTEP * 2
            cursor_x = HSTEP
        cursor_x += HSTEP
        if cursor_x >= WIDTH - HSTEP:
            cursor_y += VSTEP
            cursor_x = HSTEP
    return display_list


WIDTH, HEIGHT = 800, 600
SCROLL_STEP = 100


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<MouseWheel>", self.mousewheel)
        self.window.bind("<Configure>", self.on_configure)
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack(fill="both", expand=True)
        self.scroll = 0

    def load(self, url):
        headers, body = request(url)
        self.text = lex(body)
        self.reflow()

    def paint(self):
        self.canvas.delete("all")
        scroll_percent = self.scroll / (self.max_y - HEIGHT)
        KNOB = 30
        TOP_PADDING = VSTEP
        usable_height = HEIGHT - TOP_PADDING - KNOB
        self.canvas.create_rectangle(WIDTH - 6, VSTEP, WIDTH, HEIGHT, fill="#ccc")
        self.canvas.create_rectangle(
            WIDTH - 6,
            scroll_percent * usable_height + TOP_PADDING,
            WIDTH,
            scroll_percent * usable_height + TOP_PADDING + KNOB,
            fill="#aaa"
        )
        for x, y, c in self.display_list:
            if y > self.scroll + HEIGHT:
                continue
            if y + VSTEP < self.scroll:
                continue
            self.canvas.create_text(x, y - self.scroll, text=c)

    def on_configure(self, e):
        global WIDTH
        global HEIGHT
        # FIXME: when requesting a window of size x, y windows gives you a
        # window of size x + 4, y + 4. this is a shit hack to get all the maths
        # to work again
        WIDTH, HEIGHT = e.width - 4, e.height - 4
        pprint(e)
        self.reflow()

    def reflow(self):
        pprint((WIDTH, HEIGHT))
        self.display_list = layout(self.text)
        self.max_y = max(x[1] for x in self.display_list)
        self.paint()

    def scrolldown(self, _):
        self.scroll += SCROLL_STEP
        self.scroll = min(self.scroll, self.max_y - HEIGHT)
        self.paint()

    def scrollup(self, _):
        self.scroll -= SCROLL_STEP
        self.scroll = max(self.scroll, 0)
        self.paint()

    # TODO: mac delta is inverted, and linux doesn't even use <MouseWheel> events
    def mousewheel(self, e):
        assert e.delta != 0
        if e.delta > 0:
            self.scrollup(e)
        else:
            self.scrolldown(e)


if __name__ == "__main__":
    import sys

    Browser().load(sys.argv[1])
    tkinter.mainloop()
