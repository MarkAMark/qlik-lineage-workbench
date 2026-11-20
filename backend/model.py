from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


def key(*parts: Any) -> str:
    return hashlib.sha256('\x1f'.join(map(str, parts)).encode()).hexdigest()[:20]


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}
        self.incoming: dict[str, set[str]] = defaultdict(set)
        self.outgoing: dict[str, set[str]] = defaultdict(set)

    def add(self, kind: str, identity: Any, label: str, *, expression: str = '',
            ref: dict | None = None, confidence: str = 'parsed', **details: Any) -> str:
        node_id = f'{kind}:{key(identity)}'
        if node_id not in self.nodes:
            self.nodes[node_id] = dict(id=node_id, kind=kind, label=label,
                                      expression=expression, ref=ref,
                                      confidence=confidence, **details)
        return node_id

    def link(self, source: str, target: str, relation: str = 'value') -> None:
        if source == target:
            # Retain self references as an explicit review boundary, never recurse.
            self.nodes[target]['confidence'] = 'review'
            self.nodes[target]['note'] = '发现自引用；需要结合运行时确认。'
            return
        self.incoming[target].add(source)
        self.outgoing[source].add(target)
        self.edges[(source, target)] = dict(id=key(source, target), source=source,
                                          target=target, relation=relation)

    def ancestors(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.incoming.get(current, ()))
        return seen

    def trace(self, node_id: str) -> dict:
        ids = self.ancestors(node_id)
        nodes = [n for n in self.nodes.values() if n['id'] in ids]
        unresolved = [n for n in nodes if n['confidence'] == 'unresolved']
        review = [n for n in nodes if n['confidence'] == 'review']
        sources = [n for n in nodes if n['kind'] == 'source']
        status = 'partial' if unresolved or review else 'complete'
        if unresolved and not sources:
            status = 'unresolved'
        # Evidence is fetched separately, so a large SQL block is not repeated in the graph.
        public = [{k: v for k, v in n.items() if k not in ('expression',)} for n in nodes]
        return dict(root=node_id, nodes=public,
                    edges=[e for e in self.edges.values()
                           if e['source'] in ids and e['target'] in ids],
                    status=status, sourceCount=len(sources),
                    unresolvedCount=len(unresolved), reviewCount=len(review))


@dataclass
class Table:
    name: str
    fields: dict[str, str] = field(default_factory=dict)
    wildcards: list[dict] = field(default_factory=list)
    lineage_id: str = ''
