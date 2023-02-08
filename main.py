from enum import Enum
from pprint import pprint
import re
import socket
import ssl
from typing import Tuple, Optional
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
    x = re.match(expr, input)
    if x is None:
        return None, input
    start, end = x.span()
    return input[start:end], input[end:]


def show(body):
    # in_angle = False
    # for c in body:
    #     if c == "<":
    #         in_angle = True
    #     elif c == ">":
    #         in_angle = False
    #     elif not in_angle:
    #         print(c, end="")
    ParserState = Enum("ParserState", ["ANYTHING", "TAGNAME"])
    state = ParserState.ANYTHING
    in_body = False

    while body:
        if state == ParserState.ANYTHING:
            match, body = hawp(body, "<|[^<]+")
            if match == "<":
                state = ParserState.TAGNAME
            elif match:
                state = ParserState.ANYTHING
                if in_body:
                    print(match, end="")
            else:
                assert False
            pass
        elif state == ParserState.TAGNAME:
            # TODO: deal with > inside tags
            tag, body = hawp(body, "/?[a-zA-Z!-]+")
            assert tag
            tag = tag.lower()
            _, body = hawp(body, ".*>")
            if tag == "body":
                in_body = True
            elif tag == "/body":
                in_body = False
            state = ParserState.ANYTHING
        else:
            assert False, f"Bad parser state: {state}"


def load(url):
    headers, body = request(url)
    show(body)


if __name__ == "__main__":
    import sys

    load(sys.argv[1])
