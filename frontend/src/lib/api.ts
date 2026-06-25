// Client gọi FastAPI backend.
// URL backend cấu hình qua NEXT_PUBLIC_API_URL (mặc định localhost:8000).

import type {
  AnalyticsResponse,
  FilterOptions,
  FilterState,
  Listing,
  SummaryStats,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

/** Dựng query string từ FilterState (bỏ qua giá trị rỗng). */
function filterParams(f: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (f.minPrice != null) p.set("min_price", String(f.minPrice));
  if (f.maxPrice != null) p.set("max_price", String(f.maxPrice));
  if (f.minArea != null) p.set("min_area", String(f.minArea));
  if (f.maxArea != null) p.set("max_area", String(f.maxArea));
  for (const w of f.wards) p.append("districts", w);
  for (const t of f.propertyTypes) p.append("property_types", t);
  for (const a of f.amenities) p.append("amenities", a);
  return p;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${path} lỗi ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function getApiBase(): string {
  return API_BASE;
}

export async function fetchFilterOptions(): Promise<FilterOptions> {
  return getJSON<FilterOptions>("/api/filters/options");
}

export async function fetchListings(f: FilterState): Promise<Listing[]> {
  const qs = filterParams(f).toString();
  return getJSON<Listing[]>(`/api/listings/map${qs ? `?${qs}` : ""}`);
}

export async function fetchSummary(f: FilterState): Promise<SummaryStats> {
  const qs = filterParams(f).toString();
  return getJSON<SummaryStats>(`/api/stats/summary${qs ? `?${qs}` : ""}`);
}

export async function fetchAnalytics(f: FilterState): Promise<AnalyticsResponse> {
  const qs = filterParams(f).toString();
  return getJSON<AnalyticsResponse>(`/api/stats/analytics${qs ? `?${qs}` : ""}`);
}
