from dataclasses import dataclass
from enum import Enum
from pprint import pprint
import re
import socket
import ssl
import tkinter
import tkinter.font
from typing import Optional, Tuple
from urllib.parse import urlparse


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


@dataclass
class Text:
    text: str


@dataclass
class Tag:
    tag: str


def lex(body):
    ParserState = Enum("ParserState", ["ANYTHING", "TAGNAME"])
    state = ParserState.ANYTHING
    in_body = False
    out = []

    while body:
        if state == ParserState.ANYTHING:
            match, body = hawp(body, "<|\n+|[^<\n]+")
            assert match
            if match == "<":
                state = ParserState.TAGNAME
            elif match:
                state = ParserState.ANYTHING
                if in_body:
                    out.append(Text(match))
            pass
        elif state == ParserState.TAGNAME:
            # TODO: deal with > inside tags
            tag, body = hawp(body, "/?[a-zA-Z!-]+")
            assert tag
            tag = tag.lower()
            rest, body = hawp(body, ".*?>")
            assert rest
            if tag == "body":
                in_body = True
            elif tag == "/body":
                in_body = False
            # remove the ">" at the end of `rest`
            out.append(Tag(tag + rest[:-1]))
            state = ParserState.ANYTHING
        else:
            assert False, f"Bad parser state: {state}"
    return out


HSTEP, VSTEP = 13, 18
FONTS = {}


def get_font(size, weight, slant):
    key = (size, weight, slant)
    if key not in FONTS:
        font = tkinter.font.Font(family="Times", size=size, weight=weight, slant=slant)
        FONTS[key] = font
    return FONTS[key]


class Layout:
    def __init__(self, tokens):
        self.display_list = []
        self.cursor_x = HSTEP
        self.cursor_y = VSTEP
        self.weight = "normal"
        self.style = "roman"
        self.size = 16
        self.line = []

        for token in tokens:
            self.token(token)
        self.flush()

    def token(self, token):
        if isinstance(token, Text):
            self.text(token)
        elif token.tag == "i":
            self.style = "italic"
        elif token.tag == "/i":
            self.style = "roman"
        elif token.tag == "b":
            self.weight = "bold"
        elif token.tag == "/b":
            self.weight = "normal"
        elif token.tag == "small":
            self.size -= 2
        elif token.tag == "/small":
            self.size += 2
        elif token.tag == "big":
            self.size += 4
        elif token.tag == "/big":
            self.size -= 4
        elif token.tag == "br":
            self.flush()
        elif token.tag == "/p":
            self.flush()
            self.cursor_y += VSTEP

    def text(self, token):
        font = get_font(self.size, self.weight, self.style)
        for word in token.text.split():
            w = font.measure(word)
            if self.cursor_x + w > WIDTH - HSTEP:
                self.flush()
            self.line.append((self.cursor_x, word, font))
            self.cursor_x += w + font.measure(" ")

    def flush(self):
        if not self.line:
            return
        metrics = [font.metrics() for _, _, font in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])
        baseline = self.cursor_y + 1.25 * max_ascent
        for x, word, font in self.line:
            y = baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))
        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = HSTEP
        self.line = []


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
        _, body = request(url)
        self.tokens = lex(body)
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
            fill="#aaa",
        )
        for x, y, c, font in self.display_list:
            if y > self.scroll + HEIGHT:
                continue
            if y + VSTEP < self.scroll:
                continue
            self.canvas.create_text(x, y - self.scroll, text=c, font=font, anchor="nw")

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
        self.display_list = Layout(self.tokens).display_list
        # FIXME: why is it / 2. whatever
        self.max_y = max(x[1] + VSTEP / 2 for x in self.display_list)
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
