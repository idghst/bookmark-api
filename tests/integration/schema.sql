-- Disposable local test database only. No auth schema, RPC or RLS dependency.
CREATE SCHEMA IF NOT EXISTS bookmark;
CREATE TABLE IF NOT EXISTS bookmark.sections (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, name text NOT NULL CHECK (btrim(name) <> ''),
 color text, position integer NOT NULL DEFAULT 0 CHECK (position >= 0),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (id, user_id)
);
CREATE TABLE IF NOT EXISTS bookmark.folders (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, name text NOT NULL CHECK (btrim(name) <> ''),
 color text, position integer NOT NULL DEFAULT 0 CHECK (position >= 0), section_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (id, user_id),
 FOREIGN KEY (section_id, user_id) REFERENCES bookmark.sections(id, user_id) ON DELETE SET NULL (section_id)
);
CREATE TABLE IF NOT EXISTS bookmark.folder_sections (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, name text NOT NULL CHECK (btrim(name) <> ''),
 color text, position integer NOT NULL DEFAULT 0 CHECK (position >= 0), folder_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (id, folder_id, user_id),
 FOREIGN KEY (folder_id, user_id) REFERENCES bookmark.folders(id, user_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS bookmark.items (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, title text NOT NULL, url text NOT NULL,
 description text, is_favorite boolean DEFAULT false, color text,
 position integer NOT NULL DEFAULT 0 CHECK (position >= 0), folder_id uuid, folder_section_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY (folder_id, user_id) REFERENCES bookmark.folders(id, user_id) ON DELETE SET NULL (folder_id),
 FOREIGN KEY (folder_section_id, folder_id, user_id) REFERENCES bookmark.folder_sections(id, folder_id, user_id) ON DELETE SET NULL (folder_section_id),
 CHECK (folder_section_id IS NULL OR folder_id IS NOT NULL)
);
