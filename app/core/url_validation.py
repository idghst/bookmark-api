from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

_http_url_adapter = TypeAdapter(AnyHttpUrl)


def has_valid_host(host: str | None) -> bool:
    if not host:
        return False
    if host.startswith("[") and host.endswith("]"):
        try:
            ip_address(host[1:-1])
        except ValueError:
            return False
        return True

    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        return True

    host = host.removesuffix(".")
    if not host or len(host) > 253:
        return False
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    return all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(
            character.isascii() and (character.isalnum() or character == "-")
            for character in label
        )
        for label in ascii_host.split(".")
    )


def require_http_origin(value: object, *, allow_root_path: bool) -> str:
    if isinstance(value, AnyHttpUrl):
        value = str(value)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or any(character.isspace() for character in value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("must be a concrete HTTP(S) origin")

    try:
        raw_url = urlsplit(value)
        raw_port = raw_url.port
    except ValueError as error:
        raise ValueError("must use a valid authority") from error
    if not raw_url.netloc or raw_url.netloc.endswith(":"):
        raise ValueError("must use a valid authority")
    if raw_port is not None and not 0 < raw_port <= 65535:
        raise ValueError("must use a valid port")
    if raw_url.path not in ({"", "/"} if allow_root_path else {""}):
        raise ValueError("must be a concrete HTTP(S) origin")

    try:
        parsed_url = _http_url_adapter.validate_python(value)
    except ValidationError as error:
        raise ValueError("must be a concrete HTTP(S) origin") from error
    if (
        parsed_url.scheme not in {"http", "https"}
        or not has_valid_host(parsed_url.host)
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path != "/"
        or parsed_url.query is not None
        or parsed_url.fragment is not None
    ):
        raise ValueError("must be a concrete HTTP(S) origin")
    return value


def require_http_url(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or any(character.isspace() for character in value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("must be an HTTP(S) URL")

    try:
        raw_url = urlsplit(value)
        raw_port = raw_url.port
    except ValueError as error:
        raise ValueError("must use a valid authority") from error
    if (
        raw_url.scheme not in {"http", "https"}
        or not raw_url.netloc
        or raw_url.netloc.endswith(":")
    ):
        raise ValueError("must be an HTTP(S) URL")
    if raw_port is not None and not 0 < raw_port <= 65535:
        raise ValueError("must use a valid port")
    if raw_url.username or raw_url.password or not has_valid_host(raw_url.hostname):
        raise ValueError("must be an HTTP(S) URL")
    return value
