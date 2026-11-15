-- Роль БД и права для s_media_analyzer (ТЗ v2).
--
-- Выполняется суперпользователем (например, postgres). Расширение pgvector
-- требует суперпользователя, поэтому удобно выполнить весь скрипт один раз.

-- 1. Расширение pgvector (тип vector(512)).
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Роль анализатора.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analyzer') THEN
        CREATE ROLE analyzer LOGIN PASSWORD 'analyzer_password';
    END IF;
END
$$;

-- 3. Схема анализатора и полные права только на неё.
CREATE SCHEMA IF NOT EXISTS analysis AUTHORIZATION analyzer;
GRANT ALL PRIVILEGES ON SCHEMA analysis TO analyzer;
ALTER DEFAULT PRIVILEGES IN SCHEMA analysis GRANT ALL PRIVILEGES ON TABLES TO analyzer;
ALTER DEFAULT PRIVILEGES IN SCHEMA analysis GRANT ALL PRIVILEGES ON SEQUENCES TO analyzer;

-- 4. Только чтение каталога s_media_service (для сверки, раздел 9.7).
--    Внешних ключей на таблицы каталога у анализатора нет.
--    Схема каталога задаётся CATALOG_SCHEMA (в s_media_service обычно main).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'main') THEN
        GRANT USAGE ON SCHEMA main TO analyzer;
        GRANT SELECT ON TABLE main.storages TO analyzer;
        GRANT SELECT ON TABLE main.files TO analyzer;
    END IF;
END
$$;
