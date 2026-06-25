// Nhãn tiếng Việt + màu, đồng bộ với dashboard Streamlit (data_source.py).
// Lưu ý: dữ liệu Silver dùng mã 'phong_tro'/'chung_cu'/'nha_nguyen_can';
// dbt dim dùng 'room'/'apartment'/'house'. Map cả hai để an toàn.

export const PROPERTY_TYPE_LABELS: Record<string, string> = {
  phong_tro: "Phòng trọ",
  chung_cu: "Chung cư",
  nha_nguyen_can: "Nhà nguyên căn",
  can_ho_dich_vu: "Căn hộ dịch vụ",
  khac: "Khác",
  // dbt codes
  room: "Phòng trọ",
  apartment: "Chung cư",
  house: "Nhà nguyên căn",
  studio: "Studio",
  other: "Khác",
};

export function propertyTypeLabel(code: string | null | undefined): string {
  if (!code) return "Khác";
  return PROPERTY_TYPE_LABELS[code] ?? code;
}

export const PROPERTY_TYPE_COLORS: Record<string, string> = {
  "Phòng trọ": "#2563eb",
  "Chung cư": "#7c3aed",
  "Nhà nguyên căn": "#0891b2",
  "Căn hộ dịch vụ": "#db2777",
  Studio: "#f59e0b",
  Khác: "#94a3b8",
};

export function propertyTypeColor(code: string | null | undefined): string {
  return PROPERTY_TYPE_COLORS[propertyTypeLabel(code)] ?? "#94a3b8";
}

/** Màu theo NHÃN tiếng Việt (khi đã có sẵn label, không có code). */
export function propertyLabelColor(label: string): string {
  return PROPERTY_TYPE_COLORS[label] ?? "#94a3b8";
}

export const AMENITY_LABELS: Record<string, string> = {
  has_air_conditioner: "Điều hoà",
  has_water_heater: "Bình nóng lạnh",
  has_fridge: "Tủ lạnh",
  has_washing_machine: "Máy giặt",
  has_furniture: "Nội thất",
  has_wifi: "Wifi",
  has_kitchen: "Bếp",
  is_self_contained: "Khép kín",
  free_hours: "Giờ giấc tự do",
  landlord_shared: "Chung chủ",
  good_security: "An ninh tốt",
  near_market: "Gần chợ",
};

// Các tiện ích cho phép lọc trong sidebar (thứ tự hiển thị).
export const FILTERABLE_AMENITIES: string[] = [
  "has_air_conditioner",
  "is_self_contained",
  "has_water_heater",
  "has_washing_machine",
  "has_furniture",
  "has_fridge",
  "has_wifi",
  "has_kitchen",
  "good_security",
  "near_market",
];

export function amenityLabel(key: string): string {
  return AMENITY_LABELS[key] ?? key;
}

export const SEGMENT_LABELS: Record<string, string> = {
  thap: "Bình dân",
  trung_binh: "Trung cấp",
  cao: "Cao cấp",
};

export const SEGMENT_COLORS: Record<string, string> = {
  thap: "#16a34a",
  trung_binh: "#93c5fd",
  cao: "#dc2626",
};
