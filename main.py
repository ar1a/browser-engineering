from enum import Enum
from functools import cache
from pprint import pprint
import re
import socket
import ssl
import tkinter
import tkinter.font
from typing import Optional, Tuple
from urllib.parse import urlparse


@cache
def measure_word(font, word):
    return get_font(*font).measure(word)


@cache
def font_metrics(font, *options):
    return get_font(*font).metrics(*options)


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
    x = re.match(expr, input, flags=re.DOTALL | re.ASCII)
    if x is None:
        return None, input
    start, end = x.span()
    return input[start:end], input[end:]


class HTMLParser:
    SELF_CLOSING_TAGS = [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
    HEAD_TAGS = [
        "base",
        "basefont",
        "bgsound",
        "noscript",
        "link",
        "meta",
        "title",
        "style",
        "script",
    ]

    def __init__(self, body) -> None:
        self.body = body
        self.unfinished: list[Element | Text] = []

    def parse(self):
        ParserState = Enum("ParserState", ["ANYTHING", "TAGNAME"])
        state = ParserState.ANYTHING
        in_body = False

        while self.body:
            if state == ParserState.ANYTHING:
                match, self.body = hawp(self.body, "<|\n+|[^<\n]+")
                assert match
                if match == "<":
                    state = ParserState.TAGNAME
                elif match:
                    state = ParserState.ANYTHING
                    if in_body:
                        self.add_text(match)
                pass
            elif state == ParserState.TAGNAME:
                # TODO: deal with > inside tags
                tag, self.body = hawp(self.body, "/?[a-zA-Z!-]+")
                assert tag
                tag = tag.lower()
                rest, self.body = hawp(self.body, ".*?>")
                assert rest
                if tag == "body":
                    in_body = True
                elif tag == "/body":
                    in_body = False
                # remove the ">" at the end of `rest`
                self.add_tag(tag + rest[:-1])
                state = ParserState.ANYTHING
            else:
                assert False, f"Bad parser state: {state}"
        return self.finish()

    def add_text(self, text: str) -> None:
        if text.isspace():
            return
        self.implicit_tags(None)
        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    def add_tag(self, tag: str) -> None:
        # skip !doctype, and comments
        tag, attributes = self.get_attributes(tag)
        if tag.startswith("!"):
            return
        self.implicit_tags(tag)
        if tag.startswith("/"):
            if len(self.unfinished) == 1:
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        elif tag in self.SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def implicit_tags(self, tag: str | None) -> None:
        while True:
            open_tags = [node.tag for node in self.unfinished]
            if open_tags == [] and tag != "html":
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif (
                open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS
            ):
                self.add_tag("/head")
            else:
                break

    def finish(self):
        if len(self.unfinished) == 0:
            self.add_tag("html")
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()

    def get_attributes(self, text: str):
        parts = text.split()
        tag = parts[0].lower()
        attributes = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.lower()] = value
            else:
                attributes[attrpair.lower()] = ""
        return tag, attributes


def style(node):
    node.style = {}

    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    for child in node.children:
        style(child)


class CSSParser:
    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0

    def whitespace(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self) -> str:
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                self.i += 1
            else:
                break
        assert self.i > start, "word called when not pointing at a word"
        return self.s[start : self.i]

    def literal(self, literal) -> None:
        assert self.i < len(self.s) and self.s[self.i] == literal
        self.i += 1

    def pair(self) -> tuple[str, str]:
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()
        return prop.lower(), val

    def ignore_until(self, chars) -> str | None:
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1

    def body(self) -> dict[str, str]:
        pprint(self.s)
        pairs = {}
        while self.i < len(self.s):
            try:
                prop, val = self.pair()
                pprint((prop, val))
                pairs[prop.lower()] = val
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except AssertionError:
                why = self.ignore_until([";"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs


def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


class Text:
    def __init__(self, text, parent) -> None:
        self.text = text
        self.parent = parent
        self.children = []

    def __repr__(self) -> str:
        return repr(self.text)


class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.attributes = attributes
        self.parent = parent
        self.children = []

    def __repr__(self) -> str:
        return "<" + self.tag + ">"


HSTEP, VSTEP = 13, 18
FONTS = {}


def get_font(size, weight, slant):
    key = (size, weight, slant)
    if key not in FONTS:
        font = tkinter.font.Font(family="Times", size=size, weight=weight, slant=slant)
        FONTS[key] = font
    return FONTS[key]


class DocumentLayout:
    def __init__(self, node) -> None:
        self.node = node
        self.parent = None
        self.children = []

    def layout(self):
        self.width = WIDTH - 2 * HSTEP
        self.x = HSTEP
        self.y = VSTEP
        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        child.layout()
        self.height = child.height + 2 * VSTEP

    def paint(self, display_list):
        self.children[0].paint(display_list)


BLOCK_ELEMENTS = [
    "html",
    "body",
    "article",
    "section",
    "nav",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hgroup",
    "header",
    "footer",
    "address",
    "p",
    "hr",
    "pre",
    "blockquote",
    "ol",
    "ul",
    "menu",
    "li",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "main",
    "div",
    "table",
    "form",
    "fieldset",
    "legend",
    "details",
    "summary",
]


def layout_mode(node):
    if isinstance(node, Text):
        return "inline"
    elif node.children:
        if any(
            [
                isinstance(child, Element) and child.tag in BLOCK_ELEMENTS
                for child in node.children
            ]
        ):
            return "block"
        else:
            return "inline"
    else:
        return "block"


class DrawText:
    def __init__(self, x1, y1, text, font) -> None:
        self.top = y1
        self.left = x1
        self.text = text
        self.font = font
        self.bottom = y1 + font_metrics(font, "linespace")

    def execute(self, scroll, canvas):
        canvas.create_text(
            self.left,
            self.top - scroll,
            text=self.text,
            font=get_font(*self.font),
            anchor="nw",
        )


class DrawRect:
    def __init__(self, x1, y1, x2, y2, color) -> None:
        self.top = y1
        self.left = x1
        self.bottom = y2
        self.right = x2
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.left,
            self.top - scroll,
            self.right,
            self.bottom - scroll,
            width=0,
            fill=self.color,
        )


class BlockLayout:
    def __init__(self, node, parent, previous) -> None:
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []

    def layout(self):
        self.display_list = []
        self.x = self.parent.x
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        self.width = self.parent.width

        mode = layout_mode(self.node)
        if mode == "block":
            previous = None
            for child in self.node.children:
                next = BlockLayout(child, self, previous)
                self.children.append(next)
                previous = next
        else:
            self.cursor_x = 0
            self.cursor_y = 0
            self.weight = "normal"
            self.style = "roman"
            self.size = 16
            self.line = []

            self.recurse(self.node)
            self.flush()

        for child in self.children:
            child.layout()

        # calculate height after children are laid out
        if mode == "block":
            self.height = sum([child.height for child in self.children])
        else:
            self.height = self.cursor_y

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "small":
            self.size -= 2
        elif tag == "big":
            self.size += 4
        elif tag == "br":
            self.flush()

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        elif tag == "small":
            self.size += 2
        elif tag == "big":
            self.size -= 4
        elif tag == "p":
            self.flush()
            self.cursor_y += VSTEP

    def recurse(self, tree):
        if isinstance(tree, Text):
            self.text(tree)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def text(self, token):
        font = (self.size, self.weight, self.style)
        for word in token.text.split():
            w = measure_word(font, word)
            if self.cursor_x + w > self.width:
                self.flush()
            self.line.append((self.cursor_x, word, font))
            self.cursor_x += w + measure_word(font, " ")

    def flush(self):
        if not self.line:
            return
        metrics = [font_metrics(font) for _, _, font in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])
        baseline = self.cursor_y + 1.25 * max_ascent
        for rel_x, word, font in self.line:
            x = self.x + rel_x
            y = self.y + baseline - font_metrics(font, "ascent")
            self.display_list.append((x, y, word, font))
        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = 0
        self.line = []

    def paint(self, display_list):
        bgcolor = self.node.style.get("background-color", "transparent")
        if bgcolor != "transparent":
            x2, y2 = self.x + self.width, self.y + self.height
            rect = DrawRect(self.x, self.y, x2, y2, bgcolor)
            display_list.append(rect)
        for x, y, word, font in self.display_list:
            display_list.append(DrawText(x, y, word, font))
        for child in self.children:
            child.paint(display_list)


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
        self.nodes = HTMLParser(body).parse()
        style(self.nodes)
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
        for cmd in self.display_list:
            if cmd.top > self.scroll + HEIGHT:
                continue
            if cmd.bottom < self.scroll:
                continue
            cmd.execute(self.scroll, self.canvas)

    def on_configure(self, e):
        global WIDTH
        global HEIGHT
        # FIXME: when requesting a window of size x, y windows gives you a
        # window of size x + 4, y + 4. this is a shit hack to get all the maths
        # to work again
        WIDTH, HEIGHT = e.width - 4, e.height - 4
        self.reflow()

    def reflow(self):
        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        self.document.paint(self.display_list)
        self.max_y = self.document.height - HEIGHT
        self.paint()
        # quit()

    def scrolldown(self, _):
        self.scroll += SCROLL_STEP
        self.scroll = min(self.scroll + SCROLL_STEP, self.max_y)
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

    # 1k is not enough for html.spec.whatwg.org/multipage/
    sys.setrecursionlimit(5000)
    Browser().load(sys.argv[1])
    tkinter.mainloop()
