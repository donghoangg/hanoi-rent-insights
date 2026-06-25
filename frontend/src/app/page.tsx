"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import FilterSidebar from "../components/FilterSidebar";
import { fetchFilterOptions, fetchListings } from "../lib/api";
import type { FilterOptions, FilterState, Listing } from "../lib/types";

// Leaflet cần window → tắt SSR.
const MapView = dynamic(() => import("@/components/MapView"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full grid place-items-center text-ink-400">
      Đang tải bản đồ…
    </div>
  ),
});

const EMPTY_FILTERS: FilterState = {
  minPrice: null,
  maxPrice: null,
  minArea: null,
  maxArea: null,
  wards: [],
  propertyTypes: [],
  amenities: [],
};

export default function MapPage() {
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [listings, setListings] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Tải options filter 1 lần.
  useEffect(() => {
    fetchFilterOptions()
      .then(setOptions)
      .catch((e) => setError(String(e)));
  }, []);

  // Tải listings (debounce 350ms khi filter đổi).
  const load = useCallback((f: FilterState) => {
    setLoading(true);
    fetchListings(f)
      .then((data) => {
        setListings(data);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => load(filters), 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [filters, load]);

  return (
    <div className="flex h-full">
      <FilterSidebar
        options={options}
        filters={filters}
        onChange={setFilters}
        matchCount={listings.length}
        loading={loading}
      />
      <div className="flex-1 relative min-w-0">
        {error && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-bad text-white text-xs px-3 py-2 rounded-lg shadow-lg max-w-md">
            Lỗi tải dữ liệu: {error}. Kiểm tra backend đã chạy &amp;{" "}
            <code>NEXT_PUBLIC_API_URL</code> đúng chưa.
          </div>
        )}
        {loading && (
          <div className="absolute top-3 right-3 z-[1000] bg-white/90 text-xs px-3 py-1.5 rounded-full shadow flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            Đang tải tin…
          </div>
        )}
        <MapView listings={listings} />
      </div>
    </div>
  );
}
