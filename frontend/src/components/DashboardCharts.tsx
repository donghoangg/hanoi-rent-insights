"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type {
  AmenityPrevalence,
  AmenityPremium,
  HistogramBin,
  PropertyTypePrice,
  ScatterPoint,
  SegmentShare,
  TypeShare,
  WardPrice,
} from "@/lib/types";
import { formatVNDCompact } from "@/lib/format";
import {
  SEGMENT_COLORS,
  SEGMENT_LABELS,
  amenityLabel,
  propertyLabelColor,
  propertyTypeColor,
  propertyTypeLabel,
} from "@/lib/labels";

const GOOD = "#16a34a";
const BAD = "#dc2626";
const ACCENT = "#2563eb";
const GRID = "#eef2f7";

const AXIS = { fontSize: 11, fill: "#64748b" };
const AXIS_SM = { fontSize: 10, fill: "#64748b" };

const vndTick = (v: number) => formatVNDCompact(v);
const kTick = (v: number) => `${Math.round(v / 1000)}k`;
const pctTick = (v: number) => `${v}%`;

// ---- 1. Histogram phân bố GIÁ ---------------------------------------------

export function PriceHistogram({ data }: { data: HistogramBin[] }) {
  const rows = [...data].sort((a, b) => a.lower - b.lower);
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} margin={{ left: 4, right: 8, top: 16 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="label" tick={AXIS_SM} interval={0} angle={-30} textAnchor="end" height={50} />
        <YAxis tick={AXIS} allowDecimals={false} />
        <Tooltip formatter={tipCount} cursor={{ fill: "rgba(37,99,235,0.06)" }} />
        <Bar dataKey="count" fill={ACCENT} radius={[4, 4, 0, 0]}>
          <LabelList dataKey="count" position="top" style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 2. Histogram phân bố DIỆN TÍCH ---------------------------------------

export function AreaHistogram({ data }: { data: HistogramBin[] }) {
  const rows = [...data].sort((a, b) => a.lower - b.lower);
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} margin={{ left: 4, right: 8, top: 16 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="label" tick={AXIS_SM} interval={0} angle={-30} textAnchor="end" height={50} />
        <YAxis tick={AXIS} allowDecimals={false} />
        <Tooltip formatter={tipCount} cursor={{ fill: "rgba(8,145,178,0.06)" }} />
        <Bar dataKey="count" fill="#0891b2" radius={[4, 4, 0, 0]}>
          <LabelList dataKey="count" position="top" style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 3. Xếp hạng phường rẻ / đắt ------------------------------------------

export function WardRankChart({
  data,
  mode,
}: {
  data: WardPrice[];
  mode: "cheap" | "expensive";
}) {
  const sorted = [...data].sort((a, b) =>
    mode === "cheap"
      ? a.median_price_vnd - b.median_price_vnd
      : b.median_price_vnd - a.median_price_vnd
  );
  const top = sorted.slice(0, 10).reverse();
  const color = mode === "cheap" ? GOOD : BAD;

  if (top.length < 2) return <Empty text="Chưa đủ phường (≥10 tin) để xếp hạng." />;

  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={top} layout="vertical" margin={{ left: 8, right: 44 }}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tickFormatter={vndTick} tick={AXIS} />
        <YAxis type="category" dataKey="ward" width={88} tick={AXIS_SM} />
        <Tooltip formatter={tipMedianPrice} cursor={{ fill: "rgba(0,0,0,0.03)" }} />
        <Bar dataKey="median_price_vnd" fill={color} radius={[0, 4, 4, 0]}>
          <LabelList dataKey="median_price_vnd" position="right" formatter={vndTick} style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 4. Giá theo m² theo phường (tự tính ở backend nếu có) -----------------

export function PricePerM2Chart({ data }: { data: WardPrice[] }) {
  const top = data
    .filter((d) => d.median_price_per_m2 != null)
    .sort((a, b) => (b.median_price_per_m2 ?? 0) - (a.median_price_per_m2 ?? 0))
    .slice(0, 12)
    .reverse();

  if (top.length < 2)
    return <Empty text="Chưa đủ dữ liệu giá/m² (cột price_per_m2 trống ở nguồn)." />;

  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={top} layout="vertical" margin={{ left: 8, right: 44 }}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tickFormatter={kTick} tick={AXIS} />
        <YAxis type="category" dataKey="ward" width={88} tick={AXIS_SM} />
        <Tooltip formatter={tipPpm} cursor={{ fill: "rgba(0,0,0,0.03)" }} />
        <Bar dataKey="median_price_per_m2" radius={[0, 4, 4, 0]}>
          {top.map((_, i) => (
            <Cell key={i} fill={shadeBlue(i, top.length)} />
          ))}
          <LabelList dataKey="median_price_per_m2" position="right" formatter={kTick} style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 5. Khoảng giá theo loại hình (range p25–p75, vạch median) -------------

export function PriceBoxChart({ data }: { data: PropertyTypePrice[] }) {
  const rows = data.map((d) => ({
    name: propertyTypeLabel(d.property_type),
    q1: d.q1_price,
    span: Math.max(d.q3_price - d.q1_price, 1),
    median: d.median_price,
    color: propertyTypeColor(d.property_type),
  }));

  if (rows.length === 0) return <Empty text="Chưa có dữ liệu loại hình." />;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 48, top: 8 }}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tickFormatter={vndTick} tick={AXIS} domain={[0, "dataMax"]} />
        <YAxis type="category" dataKey="name" width={100} tick={AXIS_SM} />
        <Tooltip formatter={tipBox} cursor={{ fill: "rgba(0,0,0,0.03)" }} />
        <Bar dataKey="q1" stackId="b" fill="transparent" />
        <Bar dataKey="span" stackId="b" radius={[4, 4, 4, 4]} barSize={22}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.color} fillOpacity={0.65} />
          ))}
          <LabelList dataKey="median" position="right" formatter={vndTick} style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 6. Cơ cấu loại hình (donut + legend) ---------------------------------

export function TypeShareChart({ data }: { data: TypeShare[] }) {
  const rows = data.map((d) => ({
    name: propertyTypeLabel(d.property_type),
    value: d.count,
    color: propertyTypeColor(d.property_type),
  }));
  const total = rows.reduce((s, r) => s + r.value, 0) || 1;

  if (rows.length === 0) return <Empty text="Chưa có dữ liệu loại hình." />;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <PieChart>
        <Pie
          data={rows}
          dataKey="value"
          nameKey="name"
          innerRadius={60}
          outerRadius={95}
          paddingAngle={2}
          stroke="#fff"
          strokeWidth={2}
        >
          {rows.map((r, i) => (
            <Cell key={i} fill={r.color} />
          ))}
          <LabelList dataKey="value" position="outside" formatter={(v: number) => pctOf(v, total)} style={labelStyle} />
        </Pie>
        <Tooltip formatter={tipCount} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ---- 7. Phân khúc giá theo loại hình (stacked %) --------------------------

type SegmentRow = { name: string; thap: number; trung_binh: number; cao: number };

export function SegmentChart({ data }: { data: SegmentShare[] }) {
  const byType = new Map<string, SegmentRow>();
  for (const d of data) {
    const label = propertyTypeLabel(d.property_type);
    const row =
      byType.get(label) ?? ({ name: label, thap: 0, trung_binh: 0, cao: 0 } as SegmentRow);
    if (d.segment === "thap" || d.segment === "trung_binh" || d.segment === "cao") {
      row[d.segment] = d.count;
    }
    byType.set(label, row);
  }
  const rows = Array.from(byType.values());
  if (rows.length === 0) return <Empty text="Chưa có dữ liệu phân khúc." />;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="name" tick={AXIS_SM} />
        <YAxis tick={AXIS} allowDecimals={false} />
        <Tooltip cursor={{ fill: "rgba(0,0,0,0.03)" }} />
        <Legend formatter={segLegend} wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="thap" stackId="s" fill={SEGMENT_COLORS.thap} name="thap" />
        <Bar dataKey="trung_binh" stackId="s" fill={SEGMENT_COLORS.trung_binh} name="trung_binh" />
        <Bar dataKey="cao" stackId="s" fill={SEGMENT_COLORS.cao} name="cao" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 8. Scatter giá – diện tích -------------------------------------------

export function PriceAreaScatter({ data }: { data: ScatterPoint[] }) {
  const groups = new Map<string, ScatterPoint[]>();
  for (const d of data) {
    const k = propertyTypeLabel(d.property_type);
    const arr = groups.get(k) ?? [];
    arr.push(d);
    groups.set(k, arr);
  }
  if (data.length === 0) return <Empty text="Chưa có dữ liệu giá–diện tích." />;

  return (
    <ResponsiveContainer width="100%" height={360}>
      <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
        <CartesianGrid stroke={GRID} />
        <XAxis type="number" dataKey="area_m2" name="Diện tích" unit="m²" tick={AXIS} />
        <YAxis type="number" dataKey="price_vnd" name="Giá" tickFormatter={vndTick} tick={AXIS} />
        <ZAxis type="number" range={[24, 24]} />
        <Tooltip cursor={{ strokeDasharray: "3 3" }} formatter={tipScatter} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {Array.from(groups.entries()).map(([name, pts]) => (
          <Scatter key={name} name={name} data={pts} fill={propertyLabelColor(name)} fillOpacity={0.55} />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

// ---- 9. Premium tiện ích (diverging bar) ----------------------------------

export function AmenityPremiumChart({ data }: { data: AmenityPremium[] }) {
  if (data.length === 0)
    return <Empty text="Chưa đủ mẫu (mỗi nhóm ≥15 tin) để so chênh giá tiện ích." />;
  const rows = [...data]
    .sort((a, b) => a.pct_diff - b.pct_diff)
    .map((d) => ({ name: amenityLabel(d.amenity), pct_diff: d.pct_diff, positive: Math.sign(d.pct_diff) !== -1 }));
  const h = Math.max(280, rows.length * 34);

  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={rows} layout="vertical" margin={{ left: 12, right: 44 }}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tickFormatter={pctTick} tick={AXIS} />
        <YAxis type="category" dataKey="name" width={96} tick={AXIS_SM} />
        <Tooltip formatter={tipPct} cursor={{ fill: "rgba(0,0,0,0.03)" }} />
        <Bar dataKey="pct_diff" radius={[0, 3, 3, 0]}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.positive ? BAD : GOOD} />
          ))}
          <LabelList dataKey="pct_diff" position="right" formatter={pctSigned} style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- 10. Độ phổ biến tiện ích (% tin có) ----------------------------------

export function AmenityPrevalenceChart({ data }: { data: AmenityPrevalence[] }) {
  if (data.length === 0) return <Empty text="Chưa có dữ liệu tiện ích." />;
  const rows = [...data].sort((a, b) => a.pct - b.pct).map((d) => ({ name: amenityLabel(d.amenity), pct: d.pct }));
  const h = Math.max(280, rows.length * 34);

  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={rows} layout="vertical" margin={{ left: 12, right: 48 }}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tickFormatter={pctTick} tick={AXIS} domain={[0, 100]} />
        <YAxis type="category" dataKey="name" width={96} tick={AXIS_SM} />
        <Tooltip formatter={tipPrev} cursor={{ fill: "rgba(37,99,235,0.06)" }} />
        <Bar dataKey="pct" fill={ACCENT} radius={[0, 4, 4, 0]}>
          <LabelList dataKey="pct" position="right" formatter={pctTick} style={labelStyle} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ---- Helpers (module-level: tránh toán tử so sánh trong JSX) ---------------

const labelStyle = { fontSize: 10, fontWeight: 600, fill: "#475569" };

function Empty({ text }: { text: string }) {
  return <p className="text-xs text-ink-400 py-10 text-center">{text}</p>;
}

function shadeBlue(i: number, n: number): string {
  const a = 0.45 + (i / Math.max(n - 1, 1)) * 0.55;
  return `rgba(37,99,235,${a.toFixed(2)})`;
}

function pctOf(v: number, total: number): string {
  return `${Math.round((100 * v) / total)}%`;
}

function pctSigned(v: number): string {
  const sign = Math.sign(v) === -1 ? "" : "+";
  return `${sign}${v}%`;
}

function segLegend(v: string): string {
  return SEGMENT_LABELS[v] ?? v;
}

const tipCount = (v: number) => [`${v} tin`, "Số tin"] as [string, string];
const tipMedianPrice = (v: number) => [formatVNDCompact(v), "Giá trung vị"] as [string, string];
const tipPpm = (v: number) => [`${Math.round(v / 1000)}k/m²`, "Giá/m²"] as [string, string];
const tipPct = (v: number) => [pctSigned(v), "Chênh giá"] as [string, string];
const tipPrev = (v: number) => [`${v}%`, "Tỉ lệ tin có"] as [string, string];
const tipScatter = (v: number, n: string) =>
  (n === "Giá" ? [formatVNDCompact(v), n] : [`${v} m²`, n]) as [string, string];

function tipBox(_v: number, _n: string, p: { payload?: { q1: number; span: number; median: number } }) {
  const d = p.payload;
  if (!d) return ["", ""] as [string, string];
  const lo = formatVNDCompact(d.q1);
  const hi = formatVNDCompact(d.q1 + d.span);
  const med = formatVNDCompact(d.median);
  return [`${lo} – ${hi} (median ${med})`, "Khoảng giá p25–p75"] as [string, string];
}
