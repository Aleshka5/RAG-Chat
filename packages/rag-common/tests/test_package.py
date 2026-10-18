import rag_common


def test_package_exports_callables() -> None:
    assert callable(rag_common.authenticate)
    assert callable(rag_common.declare_topology)
    assert callable(rag_common.point_id)
    assert rag_common.PREFETCH_COUNT == 1
