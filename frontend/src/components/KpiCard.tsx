interface Props {
  label: string;
  value: string;
  sub?: string;
}

/** Thẻ KPI — phong cách tối, đồng bộ dashboard Streamlit. */
export default function KpiCard({ label, value, sub }: Props) {
  return (
    <div className="rounded-2xl border border-ink-700 bg-gradient-to-br from-ink-800 to-ink-900 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-ink-400 font-semibold">
        {label}
      </div>
      <div className="text-2xl font-bold text-white leading-tight mt-0.5">
        {value}
      </div>
      {sub && <div className="text-xs text-ink-500 mt-0.5">{sub}</div>}
    </div>
  );
}
