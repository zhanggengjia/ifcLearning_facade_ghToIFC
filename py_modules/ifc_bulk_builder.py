# ifc_bulk_builder.py
from typing import Any, List, Tuple
from Grasshopper import DataTree # type: ignore
from Grasshopper.Kernel.Data import GH_Path # type: ignore

from ifc_types import Payload

def _is_pair(x: Any) -> bool:
    return (
        isinstance(x, (list, tuple))
        and len(x) == 2
    )

def build_bulk_matdata(
    Obj: Any,
    Category: Any,
    BulkContainerId: Any,
    SchemaVersion: int = 1,
) -> Tuple[List[Payload], str]:
    """
    GH Inputs:
      Obj               (Tree) : leaf = [geo, name]
      Category          (Item) : str
      BulkContainerId   (Item) : str
      SchemaVersion     (Item) : int

    Outputs:
      MatData (list[Payload])
      Log     (str)
    """

    if Obj is None:
        return [], "bulk_builder: Obj is None."

    cat = str(Category).strip() if Category is not None else ""
    if not cat:
        raise Exception("bulk_builder: Category is required.")

    container_id = str(BulkContainerId).strip() if BulkContainerId is not None else ""
    if not container_id:
        raise Exception("bulk_builder: BulkContainerId is required.")

    matdata: List[Payload] = []
    count = 0

    # 支援 Tree / List / 單一輸入
    if hasattr(Obj, "BranchCount"):
        # DataTree
        for bi in range(Obj.BranchCount):
            branch = Obj.Branch(bi)
            path = Obj.Path(bi)

            for item in branch:
                if not _is_pair(item):
                    raise Exception(
                        f"bulk_builder: invalid leaf at path {path}: {item}"
                    )

                geo, name = item
                payload: Payload = {
                    "schema": int(SchemaVersion),
                    # 注意：Bulk 沒有 unit 概念，但為了 payload 契約一致，仍給一個佔位值
                    "unit_id": "__BULK__",
                    "name": str(name),
                    "category": cat,
                    "geo": geo,
                    "props": {
                        "scope": "BULK",
                        "container_id": container_id,
                    },
                }
                matdata.append(payload)
                count += 1

    else:
        # 非 Tree，當作 list
        for item in Obj:
            if not _is_pair(item):
                raise Exception(f"bulk_builder: invalid leaf: {item}")

            geo, name = item
            payload: Payload = {
                "schema": int(SchemaVersion),
                "unit_id": "__BULK__",
                "name": str(name),
                "category": cat,
                "geo": geo,
                "props": {
                    "scope": "BULK",
                    "container_id": container_id,
                },
            }
            matdata.append(payload)
            count += 1

    return matdata, f"bulk_builder: created {count} BULK payloads (container={container_id})."
