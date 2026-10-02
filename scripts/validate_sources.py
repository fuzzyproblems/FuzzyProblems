"""Validate current original identities, source/page mappings and local caches."""
def check_sources():
    from intake import check_active
    return check_active()
