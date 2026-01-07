"""Factory for creating outbound sinks."""

from depotgate.config import settings
from depotgate.sinks.base import OutboundSink
from depotgate.sinks.filesystem import FilesystemSink
from depotgate.sinks.http import HttpSink

# Registry of available sinks
_SINKS: dict[str, type[OutboundSink]] = {
    "filesystem": FilesystemSink,
    "http": HttpSink,
    "https": HttpSink,  # Alias for http sink
}


def get_sink(sink_type: str) -> OutboundSink:
    """
    Get a sink instance by type.

    Args:
        sink_type: Type of sink to create

    Returns:
        OutboundSink instance

    Raises:
        ValueError: If sink type is not registered
    """
    if sink_type not in _SINKS:
        raise ValueError(
            f"Unknown sink type: {sink_type}. "
            f"Available: {list(_SINKS.keys())}"
        )

    return _SINKS[sink_type]()


def get_sink_for_destination(destination: str) -> tuple[OutboundSink, str]:
    """
    Get appropriate sink for a destination string.

    Parses destination format "sink_type://path" and returns
    the sink instance and the path portion.

    Args:
        destination: Full destination string

    Returns:
        Tuple of (OutboundSink, destination_path)
    """
    if "://" in destination:
        parts = destination.split("://", 1)
        sink_type = parts[0]
        dest_path = parts[1]
    else:
        # Default to filesystem for unqualified paths
        sink_type = "filesystem"
        dest_path = destination

    return get_sink(sink_type), dest_path


def register_sink(name: str, sink_class: type[OutboundSink]) -> None:
    """
    Register a new sink type.

    Args:
        name: Name for the sink type
        sink_class: Sink class to register
    """
    _SINKS[name] = sink_class


def list_sinks() -> list[str]:
    """List available sink types."""
    return list(_SINKS.keys())


def get_enabled_sinks() -> list[OutboundSink]:
    """Get instances of all enabled sinks from config."""
    enabled = settings.get_enabled_sinks()
    return [get_sink(s) for s in enabled if s in _SINKS]
