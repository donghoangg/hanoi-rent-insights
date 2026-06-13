-- =============================================================
-- Migration: Backfill price_per_m2 cho silver.listings (data hien co)
-- =============================================================
-- Boi canh: code bronze_to_silver.py truoc day KHONG ghi price_per_m2 xuong
--   silver (cot bi bo sot trong _UPSERT_SQL). Da fix code; migration nay
--   backfill cho cac tin da ton tai. Lan ETL toi tro di se tu dien.
--
-- AN TOAN:
--   - Idempotent: chay lai nhieu lan cho cung ket qua.
--   - KHONG xoa du lieu. Chi UPDATE cot price_per_m2.
--   - Chi tinh khi co price_vnd va area_m2 > 0; nguoc lai de NULL.
--
-- Chay:
--   psql "$DATABASE_URL" -f infra/db/migration_backfill_price_per_m2.sql
-- =============================================================

BEGIN;

-- 1) Dam bao cot ton tai (an toan neu da co)
ALTER TABLE silver.listings
    ADD COLUMN IF NOT EXISTS price_per_m2 BIGINT;

-- 2) Backfill: chi cho tin co du gia + dien tich hop le
UPDATE silver.listings
SET price_per_m2 = ROUND(price_vnd::NUMERIC / area_m2)::BIGINT
WHERE price_vnd IS NOT NULL
  AND area_m2 IS NOT NULL
  AND area_m2 > 0;

-- 3) Cac tin khong du dieu kien -> dam bao NULL (khong de gia tri rac)
UPDATE silver.listings
SET price_per_m2 = NULL
WHERE price_vnd IS NULL
   OR area_m2 IS NULL
   OR area_m2 <= 0;

-- 4) Bao cao ket qua
DO $$
DECLARE
    total        BIGINT;
    has_ppm2     BIGINT;
BEGIN
    SELECT COUNT(*) INTO total FROM silver.listings;
    SELECT COUNT(price_per_m2) INTO has_ppm2 FROM silver.listings;
    RAISE NOTICE 'Backfill price_per_m2 xong: % / % tin co price_per_m2', has_ppm2, total;
END $$;

COMMIT;
