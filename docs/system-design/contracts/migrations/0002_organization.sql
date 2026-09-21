-- Named tags and collections organize existing boxes without duplicating inventory.
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE box_tags (
    box_id TEXT NOT NULL REFERENCES boxes(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (box_id, tag_id)
) STRICT;
CREATE INDEX ix_box_tags_tag_box ON box_tags(tag_id, box_id);

CREATE TABLE collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE collection_boxes (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    box_id TEXT NOT NULL REFERENCES boxes(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, box_id)
) STRICT;
CREATE INDEX ix_collection_boxes_box_collection ON collection_boxes(box_id, collection_id);

DROP TABLE box_search;
CREATE VIRTUAL TABLE box_search USING fts5(
    box_id UNINDEXED,
    code,
    name,
    description,
    item_names,
    item_notes,
    tag_names,
    collection_names,
    tokenize = 'unicode61 remove_diacritics 2'
);

INSERT INTO box_search (box_id, code, name, description, item_names, item_notes, tag_names, collection_names)
SELECT b.id, b.public_code, b.name, b.description_text,
    coalesce((SELECT group_concat(name, char(10)) FROM (
        SELECT i.name FROM inventory_items i WHERE i.box_id = b.id AND i.lifecycle = 'active' ORDER BY i.id
    )), ''),
    coalesce((SELECT group_concat(notes_text, char(10)) FROM (
        SELECT i.notes_text FROM inventory_items i WHERE i.box_id = b.id AND i.lifecycle = 'active' ORDER BY i.id
    )), ''),
    coalesce((SELECT group_concat(name, char(10)) FROM (
        SELECT t.name FROM tags t JOIN box_tags bt ON bt.tag_id = t.id WHERE bt.box_id = b.id ORDER BY t.id
    )), ''),
    coalesce((SELECT group_concat(name, char(10)) FROM (
        SELECT c.name FROM collections c JOIN collection_boxes cb ON cb.collection_id = c.id
        WHERE cb.box_id = b.id ORDER BY c.id
    )), '')
FROM boxes b;

UPDATE search_projection_state SET
    projection_version = 'box-search-v2',
    last_rebuilt_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    last_verified_at = NULL,
    source_row_count = (SELECT count(*) FROM boxes),
    projection_row_count = (SELECT count(*) FROM box_search),
    state = 'ready'
WHERE singleton = 1;
