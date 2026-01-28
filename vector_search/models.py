from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class VectorSearchFilters:
    data_type: Optional[List[str]] = None
    file_type: Optional[List[str]] = None
    kind: Optional[List[str]] = None
    project: Optional[List[str]] = None
    schema: Optional[List[str]] = None
    name_prefix: Optional[List[str]] = None
    branch: Optional[List[str]] = None
    db_key_in: Optional[List[str]] = None
    cs_key_in: Optional[List[str]] = None    
      # ACL: document must contain ALL required tags.
    permission_tags_all: Optional[List[str]] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorSearchRequest:
    text_query: str
    top_k: int = 10
    oversample_factor: int = 5
    filters: VectorSearchFilters = field(default_factory=VectorSearchFilters)
    include_text_preview: bool = True
