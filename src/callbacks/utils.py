from rio_tiler.colormap import ColorMaps


def convert_colormap_to_colorscale(cmap: str):
    """
    Convert a rio_tiler colormap to colorscale format.

    This function uses the `ColorMaps` utility to get the RGB and alpha values for each
    color in the specified colormap, then formats them as strings suitable for use with
    Dash-leaflet [Colorbar](https://www.dash-leaflet.com/components/controls/colorbar).

    Args:
        cmap: The name of the rio_tiler colormap to convert.

    Returns:
        A list of rgba color tuples in colorscale format.
            Each tuple is represented as a string with the format "rgba(R,G,B,A)".

    Example:
        >>> convert_colormap_to_colorscale("viridis")
        [
            'rgba(68,1,84,1.0)',
            ...
            'rgba(253,231,36,1.0)'
        ]
    """
    cmap_dict = ColorMaps().get(cmap)
    colorscale = [
        f"rgba({cmap_dict[i][0]},{cmap_dict[i][1]},{cmap_dict[i][2]},{cmap_dict[i][3] / 255})"
        for i in range(len(cmap_dict))
    ]
    return colorscale
