"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import FilterSidebar from "../../components/FilterSidebar";
import KpiCard from "../../components/KpiCard";
import {
  AmenityPremiumChart,
  AmenityPrevalenceChart,
  AreaHistogram,
  PriceAreaScatter,
  PriceBoxChart,
  PriceHistogram,
  SegmentChart,
  TypeShareChart,
  WardRankChart,
} from "../../components/DashboardCharts";
import { fetchAnalytics, fetchFilterOptions } from "../../lib/api";
import type { AnalyticsResponse, FilterOptions, FilterState } from "../../lib/types";
import { formatInt, formatVNDCompact } from "../../lib/format";

const EMPTY_FILTERS: FilterState = {
  minPrice: null,
  maxPrice: null,
  minArea: null,
  maxArea: null,
  wards: [],
  propertyTypes: [],
  amenities: [],
};

function ChartCard({
  title,
  subtitle,
  children,
  span,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  span?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border border-ink-700/10 bg-white p-4 shadow-sm ${
        span ? "lg:col-span-2" : ""
      }`}
    >
      <h3 className="font-semibold text-sm text-ink-900">{title}</h3>
      {subtitle ? <p className="text-xs text-ink-400 mb-1">{subtitle}</p> : null}
      <div className="mt-2">{children}</div>
    </div>
  );
}

export default function DashboardPage() {
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetchFilterOptions()
      .then(setOptions)
      .catch((e) => setError(String(e)));
  }, []);

  const load = useCallback((f: FilterState) => {
    setLoading(true);
    fetchAnalytics(f)
      .then((d) => {
        setData(d);
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

  const s = data?.summary;
  const topType =
    data && data.type_shares.length > 0
      ? data.type_shares.reduce((a, b) => (a.count >= b.count ? a : b))
      : null;

  return (
    <div className="flex h-full">
      <FilterSidebar
        options={options}
        filters={filters}
        onChange={setFilters}
        matchCount={s?.total_listings ?? null}
        loading={loading}
      />

      <div className="flex-1 overflow-y-auto thin-scroll bg-ink-900/[0.02] min-w-0">
        <div className="p-5 max-w-[1500px] mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-xl font-bold text-ink-900">
                Phân tích thị trường thuê nhà Hà Nội
              </h1>
              <p className="text-sm text-ink-500">
                Tra mặt bằng giá theo khu vực · đã loại giá bất thường (outlier) ·
                nguồn Nhatot + Mogi.
              </p>
            </div>
            {loading ? (
              <span className="text-xs text-ink-400 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
                Đang tải…
              </span>
            ) : null}
          </div>

          {error ? (
            <div className="mb-4 bg-bad/10 text-bad text-sm px-3 py-2 rounded-lg">
              Lỗi tải dữ liệu: {error}. Kiểm tra backend &amp;{" "}
              <code>NEXT_PUBLIC_API_URL</code>.
            </div>
          ) : null}

          {/* KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <KpiCard
              label="Số tin phân tích"
              value={formatInt(s?.total_listings)}
              sub={`trên ${formatInt(s?.ward_count)} phường`}
            />
            <KpiCard
              label="Giá thuê trung vị"
              value={formatVNDCompact(s?.median_price_vnd)}
              sub="đồng/tháng"
            />
            <KpiCard
              label="Khoảng giá phổ biến"
              value={`${formatVNDCompact(s?.p25_price_vnd)}–${formatVNDCompact(
                s?.p75_price_vnd
              )}`}
              sub="p25–p75 (50% số tin)"
            />
            <KpiCard
              label="Loại hình nhiều nhất"
              value={topType ? labelType(topType.property_type) : "—"}
              sub={topType ? `${formatInt(topType.count)} tin` : ""}
            />
          </div>

          {data ? (
            <div className="grid lg:grid-cols-2 gap-4">
              {/* Hàng 1: phân bố giá + diện tích (histogram) */}
              <ChartCard
                title="Phân bố giá thuê"
                subtitle="Số tin theo từng mức giá/tháng"
              >
                <PriceHistogram data={data.price_histogram} />
              </ChartCard>
              <ChartCard
                title="Phân bố diện tích"
                subtitle="Số tin theo từng khoảng diện tích"
              >
                <AreaHistogram data={data.area_histogram} />
              </ChartCard>

              {/* Hàng 2: xếp hạng phường */}
              <ChartCard
                title="10 phường RẺ nhất"
                subtitle="Giá trung vị · phường có ≥10 tin"
              >
                <WardRankChart data={data.ward_prices} mode="cheap" />
              </ChartCard>
              <ChartCard
                title="10 phường ĐẮT nhất"
                subtitle="Giá trung vị · phường có ≥10 tin"
              >
                <WardRankChart data={data.ward_prices} mode="expensive" />
              </ChartCard>

              {/* Hàng 3: cơ cấu loại hình + khoảng giá theo loại hình */}
              <ChartCard
                title="Cơ cấu nguồn cung theo loại hình"
                subtitle="Tỉ trọng số tin mỗi loại"
              >
                <TypeShareChart data={data.type_shares} />
              </ChartCard>
              <ChartCard
                title="Khoảng giá theo loại hình"
                subtitle="Thanh = p25→p75; nhãn = giá trung vị"
              >
                <PriceBoxChart data={data.type_prices} />
              </ChartCard>

              {/* Hàng 4: scatter (rộng) */}
              <ChartCard
                title="Tương quan Giá – Diện tích"
                subtitle="Mỗi điểm là một tin; điểm thấp so với cùng diện tích = rẻ hơn mặt bằng"
                span
              >
                <PriceAreaScatter data={data.scatter} />
              </ChartCard>

              {/* Hàng 5: premium tiện ích + độ phổ biến tiện ích */}
              <ChartCard
                title="Có tiện ích thì giá chênh bao nhiêu?"
                subtitle="So giá trung vị tin CÓ vs KHÔNG (mỗi nhóm ≥15 tin). Là tương quan, chưa loại ảnh hưởng khu vực/diện tích."
              >
                <AmenityPremiumChart data={data.amenity_premiums} />
              </ChartCard>
              <ChartCard
                title="Độ phổ biến tiện ích"
                subtitle="% tin đề cập có tiện ích đó"
              >
                <AmenityPrevalenceChart data={data.amenity_prevalence} />
              </ChartCard>

              {/* Hàng 6: phân khúc giá (rộng) */}
              <ChartCard
                title="Phân khúc giá theo loại hình"
                subtitle="Chia theo p33/p67 trong từng loại hình (bình dân / trung cấp / cao cấp)"
                span
              >
                <SegmentChart data={data.segment_shares} />
              </ChartCard>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function labelType(code: string): string {
  const map: Record<string, string> = {
    phong_tro: "Phòng trọ",
    chung_cu: "Chung cư",
    nha_nguyen_can: "Nhà nguyên căn",
    can_ho_dich_vu: "Căn hộ DV",
    room: "Phòng trọ",
    apartment: "Chung cư",
    house: "Nhà nguyên căn",
  };
  return map[code] ?? code;
}
