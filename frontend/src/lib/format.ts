// Hàm định dạng dùng chung.

/** Định dạng tiền gọn: 2.500.000 → "2,5 tr"; 850.000 → "850k". */
export function formatVNDCompact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (v >= 1_000_000) {
    return `${(v / 1_000_000).toFixed(1).replace(".", ",")} tr`;
  }
  if (v >= 1_000) {
    return `${Math.round(v / 1_000)}k`;
  }
  return `${Math.round(v)}`;
}

/** Định dạng tiền đầy đủ: 2500000 → "2.500.000 đ". */
export function formatVNDFull(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v).toLocaleString("vi-VN")} đ`;
}

/** Định dạng giá/m²: 120000 → "120k/m²". */
export function formatPricePerM2(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v / 1000)}k/m²`;
}

/** Số nguyên có dấu phân cách: 1247 → "1.247". */
export function formatInt(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "0";
  return Math.round(v).toLocaleString("vi-VN");
}
