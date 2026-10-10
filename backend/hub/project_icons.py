"""Curated Lucide icon identifiers; metadata never contains remote assets or SVG."""

from typing import Literal, get_args

ProjectIcon = Literal[
    "folder",
    "briefcase",
    "building-2",
    "house",
    "code-2",
    "terminal",
    "flask-conical",
    "lightbulb",
    "book-open",
    "graduation-cap",
    "palette",
    "pen-tool",
    "music",
    "camera",
    "globe",
    "compass",
    "map",
    "plane",
    "rocket",
    "target",
    "chart-no-axes-combined",
    "presentation",
    "users",
    "heart",
    "leaf",
    "coffee",
    "wrench",
    "shield",
    "database",
    "cpu",
    "sparkles",
    "layers",
]
PROJECT_ICONS: tuple[str, ...] = get_args(ProjectIcon)
DEFAULT_PROJECT_ICON: ProjectIcon = "folder"
