// Kiểu dữ liệu khớp với response của FastAPI backend.

export interface Listing {
  listing_key: number;
  title: string | null;
  price_vnd: number | null;
  area_m2: number | null;
  price_per_m2: number | null;
  bedrooms: number | null;
  property_type: string | null;
  price_segment: string | null; // 'thap' | 'trung_binh' | 'cao'
  province: string | null;
  ward: string | null;
  latitude: number;
  longitude: number;
  source_name: string | null;
  source_url: string | null;
  thumbnail_url: string | null;
  posted_at: string | null;
  has_air_conditioner: boolean | null;
  has_water_heater: boolean | null;
  has_fridge: boolean | null;
  has_washing_machine: boolean | null;
  has_furniture: boolean | null;
  has_wifi: boolean | null;
  has_kitchen: boolean | null;
  is_self_contained: boolean | null;
  free_hours: boolean | null;
  landlord_shared: boolean | null;
  good_security: boolean | null;
  near_market: boolean | null;
}

export interface SummaryStats {
  total_listings: number;
  median_price_vnd: number | null;
  p25_price_vnd: number | null;
  p75_price_vnd: number | null;
  median_price_per_m2: number | null;
  ward_count: number;
}

export interface WardOption {
  ward: string;
  count: number;
}

export interface PropertyTypeOption {
  code: string;
  count: number;
}

export interface FilterOptions {
  wards: WardOption[];
  property_types: PropertyTypeOption[];
  price_min_vnd: number;
  price_max_vnd: number;
  area_min_m2: number;
  area_max_m2: number;
}

export interface WardPrice {
  ward: string;
  count: number;
  median_price_vnd: number;
  median_price_per_m2: number | null;
}

export interface PropertyTypePrice {
  property_type: string;
  count: number;
  min_price: number;
  q1_price: number;
  median_price: number;
  q3_price: number;
  max_price: number;
}

export interface TypeShare {
  property_type: string;
  count: number;
}

export interface ScatterPoint {
  area_m2: number;
  price_vnd: number;
  property_type: string | null;
}

export interface AmenityPremium {
  amenity: string;
  pct_diff: number;
  vnd_diff: number;
  n_with: number;
  n_without: number;
}

export interface SegmentShare {
  property_type: string;
  segment: string;
  count: number;
}


export interface HistogramBin {
  label: string;
  lower: number;
  count: number;
}

export interface AmenityPrevalence {
  amenity: string;
  pct: number;
  count: number;
}

export interface AnalyticsResponse {
  summary: SummaryStats;
  ward_prices: WardPrice[];
  type_prices: PropertyTypePrice[];
  type_shares: TypeShare[];
  scatter: ScatterPoint[];
  amenity_premiums: AmenityPremium[];
  segment_shares: SegmentShare[];
  price_histogram: HistogramBin[];
  area_histogram: HistogramBin[];
  amenity_prevalence: AmenityPrevalence[];
}

// Trạng thái bộ lọc dùng chung giữa sidebar và các trang.
export interface FilterState {
  minPrice: number | null;
  maxPrice: number | null;
  minArea: number | null;
  maxArea: number | null;
  wards: string[];
  propertyTypes: string[];
  amenities: string[];
}
