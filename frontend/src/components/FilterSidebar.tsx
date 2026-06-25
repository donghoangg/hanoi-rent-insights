"use client";

import { useMemo, useState } from "react";
import type { FilterOptions, FilterState } from "../lib/types";
import {
  FILTERABLE_AMENITIES,
  amenityLabel,
  propertyTypeLabel,
} from "../lib/labels";
import { formatInt, formatVNDCompact } from "../lib/format";

interface Props {
  options: FilterOptions | null;
  filters: FilterState;
  onChange: (f: FilterState) => void;
  /** Số tin hiện khớp filter (hiển thị ở đáy). */
  matchCount: number | null;
  loading?: boolean;
}

/**
 * Sidebar bộ lọc dùng chung cho trang Bản đồ và Phân tích.
 * Slider giá/diện tích dùng input range kép (min + max).
 */
export default function FilterSidebar({
  options,
  filters,
  onChange,
  matchCount,
  loading,
}: Props) {
  const [wardSearch, setWardSearch] = useState("");

  const priceMax = options?.price_max_vnd ?? 30_000_000;
  const areaMax = Math.ceil(options?.area_max_m2 ?? 150);

  const set = (patch: Partial<FilterState>) =>
    onChange({ ...filters, ...patch });

  const toggleType = (code: string) => {
    const next = filters.propertyTypes.includes(code)
      ? filters.propertyTypes.filter((t) => t !== code)
      : [...filters.propertyTypes, code];
    set({ propertyTypes: next });
  };

  const toggleAmenity = (key: string) => {
    const next = filters.amenities.includes(key)
      ? filters.amenities.filter((a) => a !== key)
      : [...filters.amenities, key];
    set({ amenities: next });
  };

  const toggleWard = (ward: string) => {
    const next = filters.wards.includes(ward)
      ? filters.wards.filter((w) => w !== ward)
      : [...filters.wards, ward];
    set({ wards: next });
  };

  const visibleWards = useMemo(() => {
    if (!options) return [];
    const q = wardSearch.trim().toLowerCase();
    return options.wards
      .filter((w) => (q ? w.ward.toLowerCase().includes(q) : true))
      .slice(0, q ? 60 : 40);
  }, [options, wardSearch]);

  const reset = () =>
    onChange({
      minPrice: null,
      maxPrice: null,
      minArea: null,
      maxArea: null,
      wards: [],
      propertyTypes: [],
      amenities: [],
    });

  const curMinPrice = filters.minPrice ?? 0;
  const curMaxPrice = filters.maxPrice ?? priceMax;
  const curMinArea = filters.minArea ?? 0;
  const curMaxArea = filters.maxArea ?? areaMax;

  return (
    <aside className="w-72 shrink-0 bg-white border-r border-ink-700/10 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-ink-700/10 flex items-center justify-between">
        <h2 className="font-semibold text-sm flex items-center gap-2">
          <span>🔎</span> Bộ lọc
        </h2>
        <button
          onClick={reset}
          className="text-xs text-accent hover:underline"
          type="button"
        >
          Đặt lại
        </button>
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll px-4 py-4 space-y-6 text-sm">
        {/* Loại hình */}
        <div>
          <label className="block font-semibold mb-2 text-ink-800">
            Loại hình
          </label>
          <div className="flex flex-wrap gap-1.5">
            {(options?.property_types ?? []).map((t) => {
              const active = filters.propertyTypes.includes(t.code);
              return (
                <button
                  key={t.code}
                  type="button"
                  onClick={() => toggleType(t.code)}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    active
                      ? "bg-accent text-white border-accent"
                      : "bg-white text-ink-800 border-ink-700/20 hover:border-accent"
                  }`}
                >
                  {propertyTypeLabel(t.code)}{" "}
                  <span className={active ? "opacity-80" : "text-ink-400"}>
                    {t.count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Khoảng giá */}
        <div>
          <label className="block font-semibold mb-1 text-ink-800">
            Khoảng giá / tháng
          </label>
          <div className="text-xs text-ink-500 mb-2">
            {formatVNDCompact(curMinPrice)} – {formatVNDCompact(curMaxPrice)}
          </div>
          <RangeSlider
            min={0}
            max={priceMax}
            step={500_000}
            low={curMinPrice}
            high={curMaxPrice}
            onChange={(lo, hi) =>
              set({
                minPrice: lo <= 0 ? null : lo,
                maxPrice: hi >= priceMax ? null : hi,
              })
            }
          />
        </div>

        {/* Diện tích */}
        <div>
          <label className="block font-semibold mb-1 text-ink-800">
            Diện tích (m²)
          </label>
          <div className="text-xs text-ink-500 mb-2">
            {curMinArea} – {curMaxArea} m²
          </div>
          <RangeSlider
            min={0}
            max={areaMax}
            step={5}
            low={curMinArea}
            high={curMaxArea}
            onChange={(lo, hi) =>
              set({
                minArea: lo <= 0 ? null : lo,
                maxArea: hi >= areaMax ? null : hi,
              })
            }
          />
        </div>

        {/* Tiện ích */}
        <div>
          <label className="block font-semibold mb-2 text-ink-800">
            Tiện ích
          </label>
          <div className="flex flex-wrap gap-1.5">
            {FILTERABLE_AMENITIES.map((key) => {
              const active = filters.amenities.includes(key);
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleAmenity(key)}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    active
                      ? "bg-good text-white border-good"
                      : "bg-white text-ink-800 border-ink-700/20 hover:border-good"
                  }`}
                >
                  {amenityLabel(key)}
                </button>
              );
            })}
          </div>
        </div>

        {/* Phường */}
        <div>
          <label className="block font-semibold mb-2 text-ink-800">
            Phường / khu vực
          </label>
          {filters.wards.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {filters.wards.map((w) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => toggleWard(w)}
                  className="px-2 py-0.5 rounded-full text-xs bg-accent/10 text-accent border border-accent/30"
                >
                  {w} ✕
                </button>
              ))}
            </div>
          )}
          <input
            value={wardSearch}
            onChange={(e) => setWardSearch(e.target.value)}
            placeholder="Tìm phường…"
            className="w-full px-2.5 py-1.5 rounded-lg border border-ink-700/20 text-xs mb-2 focus:outline-none focus:border-accent"
          />
          <div className="max-h-40 overflow-y-auto thin-scroll space-y-0.5 pr-1">
            {visibleWards.map((w) => {
              const active = filters.wards.includes(w.ward);
              return (
                <button
                  key={w.ward}
                  type="button"
                  onClick={() => toggleWard(w.ward)}
                  className={`w-full flex items-center justify-between px-2 py-1 rounded-md text-xs text-left ${
                    active ? "bg-accent/10 text-accent" : "hover:bg-ink-900/5"
                  }`}
                >
                  <span>{w.ward}</span>
                  <span className="text-ink-400">{w.count}</span>
                </button>
              );
            })}
            {visibleWards.length === 0 && (
              <p className="text-xs text-ink-400 py-2">Không tìm thấy phường.</p>
            )}
          </div>
        </div>
      </div>

      {/* Đếm số tin */}
      <div className="px-4 py-3 border-t border-ink-700/10 bg-ink-900 text-white">
        <div className="text-[11px] uppercase tracking-wide text-ink-400 font-semibold">
          Số tin khớp lọc
        </div>
        <div className="text-xl font-bold">
          {loading ? (
            <span className="text-ink-400 text-base">Đang tải…</span>
          ) : (
            <>
              {matchCount != null ? formatInt(matchCount) : "—"}{" "}
              <span className="text-sm font-normal text-ink-400">tin</span>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}

/**
 * Range slider kép (2 con trượt) chồng nhau — đủ dùng, không cần thư viện.
 */
function RangeSlider({
  min,
  max,
  step,
  low,
  high,
  onChange,
}: {
  min: number;
  max: number;
  step: number;
  low: number;
  high: number;
  onChange: (lo: number, hi: number) => void;
}) {
  const pct = (v: number) => ((v - min) / (max - min)) * 100;
  return (
    <div className="relative h-6">
      {/* track */}
      <div className="absolute top-1/2 -translate-y-1/2 w-full h-1 rounded bg-ink-700/15" />
      <div
        className="absolute top-1/2 -translate-y-1/2 h-1 rounded bg-accent"
        style={{ left: `${pct(low)}%`, right: `${100 - pct(high)}%` }}
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={low}
        onChange={(e) => {
          const v = Math.min(Number(e.target.value), high - step);
          onChange(v, high);
        }}
        className="range-thumb absolute w-full top-1/2 -translate-y-1/2 appearance-none bg-transparent pointer-events-none"
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={high}
        onChange={(e) => {
          const v = Math.max(Number(e.target.value), low + step);
          onChange(low, v);
        }}
        className="range-thumb absolute w-full top-1/2 -translate-y-1/2 appearance-none bg-transparent pointer-events-none"
      />
      <style jsx>{`
        .range-thumb::-webkit-slider-thumb {
          -webkit-appearance: none;
          pointer-events: auto;
          height: 16px;
          width: 16px;
          border-radius: 9999px;
          background: #2563eb;
          border: 2px solid #fff;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
          cursor: pointer;
        }
        .range-thumb::-moz-range-thumb {
          pointer-events: auto;
          height: 16px;
          width: 16px;
          border-radius: 9999px;
          background: #2563eb;
          border: 2px solid #fff;
          cursor: pointer;
        }
      `}</style>
    </div>
  );
}
