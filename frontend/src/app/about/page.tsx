export default function AboutPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-10 overflow-y-auto h-full">
      <h1 className="text-2xl font-bold mb-2">Về HanoiRent Insights</h1>
      <p className="text-ink-500 mb-6">
        Nền tảng phân tích &amp; tìm kiếm nhà cho thuê tại Hà Nội dựa trên dữ
        liệu thị trường thực tế.
      </p>

      <section className="space-y-4 text-sm leading-relaxed text-ink-800">
        <p>
          Dự án thu thập tin đăng cho thuê từ <strong>Nhatot.com</strong> và{" "}
          <strong>Mogi.vn</strong>, làm sạch và chuẩn hoá theo kiến trúc dữ liệu{" "}
          <strong>Medallion (Bronze → Silver → Gold)</strong>, rồi phục vụ qua
          website này gồm hai phần: bản đồ tra cứu tương tác và dashboard phân
          tích thị trường.
        </p>
        <p>
          Toạ độ hiển thị trên bản đồ được geocode ở <em>cấp phường</em> (dùng
          OpenStreetMap Nominatim, miễn phí), nên các marker trong cùng một
          phường được thêm độ lệch ngẫu nhiên nhỏ (±~100m) để không chồng lên
          nhau. Vì vậy vị trí marker mang tính tương đối, không phải địa chỉ
          chính xác từng số nhà — hãy bấm <strong>&quot;Xem tin gốc&quot;</strong>{" "}
          để xem thông tin đầy đủ trên website nguồn.
        </p>
        <p>
          Các chỉ số giá chỉ tính trên tin có giá hợp lệ và đã loại bỏ giá bất
          thường (outlier) bằng phương pháp IQR, đảm bảo mặt bằng giá phản ánh
          đúng thực tế.
        </p>
      </section>

      <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          ["Nguồn dữ liệu", "Nhatot · Mogi"],
          ["Kiến trúc", "Medallion"],
          ["Bản đồ", "Leaflet + OSM"],
          ["Backend", "FastAPI"],
        ].map(([k, v]) => (
          <div
            key={k}
            className="rounded-xl border border-ink-700/10 bg-white p-3"
          >
            <div className="text-[11px] uppercase tracking-wide text-ink-400 font-semibold">
              {k}
            </div>
            <div className="text-sm font-semibold mt-0.5">{v}</div>
          </div>
        ))}
      </div>

      <p className="mt-8 text-xs text-ink-400">
        Đồ án tốt nghiệp · Phân tích dữ liệu &amp; website nhà cho thuê Hà Nội.
      </p>
    </div>
  );
}
