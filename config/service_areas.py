"""Service-area eligibility policy for the synthetic demo."""

SUPPORTED_SERVICE_AREAS = frozenset({
    "DEMO-NORTH",
})


def check_service_area(service_area_id: str | None) -> tuple[bool, str]:
    """Return whether a lead belongs to a supported service area."""

    if not service_area_id:
        return False, "missing_service_area"

    normalized_area = service_area_id.strip().upper()

    if normalized_area not in SUPPORTED_SERVICE_AREAS:
        return False, "outside_service_area"

    return True, "service_area_supported"