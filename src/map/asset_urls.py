"""Rewrite STAC asset hrefs for TiTiler on the Docker network."""


def to_tiler_asset_url(
    href: str, file_server_url: str, file_server_internal_url: str
) -> str:
    """
    Rewrite public file-server hrefs so TiTiler can open them efficiently.

    Paths under ``/data/`` become ``file:///data/...`` (TiTiler mounts
    ``./data`` at ``/data``). Other matched hrefs keep an internal HTTP
    rewrite. Public STAC/QGIS hrefs stay HTTP at the source; only the
    TiTiler ``url`` query parameter is rewritten.

    Args:
        href: Public or already-internal asset href.
        file_server_url: Public file-server prefix used in STAC hrefs.
        file_server_internal_url: File-server URL reachable from TiTiler
            (fallback when the path is not under ``/data/``).

    Returns:
        Href suitable for TiTiler's ``url`` query parameter.
    """
    if not href or href.startswith("file://"):
        return href

    public = (file_server_url or "").rstrip("/")
    internal = (file_server_internal_url or "").rstrip("/")

    path = None
    for prefix in (public, internal):
        if prefix and (href == prefix or href.startswith(prefix + "/")):
            path = href[len(prefix) :] or "/"
            break

    if path is None:
        return href

    if not path.startswith("/"):
        path = "/" + path

    # Local mount on the titiler service (compose: ./data:/data:ro).
    if path == "/data" or path.startswith("/data/"):
        return "file://" + path

    if internal:
        return internal + path
    return href
