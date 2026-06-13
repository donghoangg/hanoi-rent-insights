"use client";

import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import L from "leaflet";
import type { Listing } from "@/lib/types";
import { formatVNDFull } from "@/lib/format";
import { AMENITY_LABELS, propertyTypeLabel } from "@/lib/labels";

const HANOI_CENTER: [number, number] = [21.0285, 105.8542];

type SovereigntyLabel = { name: string; pos: [number, number] };

const VN_SOVEREIGNTY: SovereigntyLabel[] = [
  { name: "Quần đảo Hoàng Sa\n(Việt Nam)", pos: [16.5, 112.0] },
  { name: "Quần đảo Trường Sa\n(Việt Nam)", pos: [10.0, 114.0] },
];

const POPUP_AMENITIES: (keyof Listing)[] = [
  "has_air_conditioner",
  "is_self_contained",
  "has_water_heater",
  "has_washing_machine",
  "has_furniture",
  "has_fridge",
  "has_wifi",
  "good_security",
];

function seededJitter(key: number): [number, number] {
  const s = Math.sin(key * 12.9898) * 43758.5453;
  const r1 = (s - Math.floor(s)) * 2 - 1;
  const s2 = Math.sin(key * 78.233) * 12543.123;
  const r2 = (s2 - Math.floor(s2)) * 2 - 1;
  const dLat = r1 * 0.0009;
  const dLng = (r2 * 0.0009) / Math.cos((HANOI_CENTER[0] * Math.PI) / 180);
  return [dLat, dLng];
}

function compactPrice(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (v >= 1000000) return `${(v / 1000000).toFixed(1).replace(".", ",")} tr`;
  if (v >= 1000) return `${Math.round(v / 1000)}k`;
  return `${Math.round(v)}`;
}

function priceIcon(listing: Listing): L.DivIcon {
  const seg = listing.price_segment ?? "trung_binh";
  const label = compactPrice(listing.price_vnd);
  return L.divIcon({
    className: "price-marker",
    html: `<div class="price-pill seg-${seg}">${label}</div>`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  });
}

function sovereigntyIcon(name: string): L.DivIcon {
  const html = name
    .split("\n")
    .map((line) => `<span>${line}</span>`)
    .join("<br/>");
  return L.divIcon({
    className: "sovereignty-marker",
    html: `<div class="sovereignty-label">${html}</div>`,
    iconSize: [120, 0],
    iconAnchor: [60, 0],
  });
}

function InitialView() {
  const map = useMap();
  useEffect(() => {
    map.setView(HANOI_CENTER, 12);
  }, [map]);
  return null;
}

interface Props {
  listings: Listing[];
}

export default function MapView({ listings }: Props) {
  const points = useMemo(
    () =>
      listings
        .filter((l) => l.latitude != null && l.longitude != null)
        .map((l) => {
          const [dLat, dLng] = seededJitter(l.listing_key);
          return {
            listing: l,
            pos: [l.latitude + dLat, l.longitude + dLng] as [number, number],
          };
        }),
    [listings]
  );

  return (
    <MapContainer
      center={HANOI_CENTER}
      zoom={12}
      className="w-full h-full"
      scrollWheelZoom
      preferCanvas
    >
      <InitialView />
      <TileLayer
        attribution="&copy; OpenStreetMap &copy; CARTO"
        url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        subdomains="abcd"
        maxZoom={20}
      />
      {VN_SOVEREIGNTY.map((isl) => (
        <Marker
          key={isl.name}
          position={isl.pos}
          icon={sovereigntyIcon(isl.name)}
          interactive={false}
          keyboard={false}
        />
      ))}
      <MarkerClusterGroup
        chunkedLoading
        maxClusterRadius={48}
        spiderfyOnMaxZoom
        showCoverageOnHover={false}
      >
        {points.map(({ listing, pos }) => (
          <Marker
            key={listing.listing_key}
            position={pos}
            icon={priceIcon(listing)}
          >
            <Popup>
              <ListingPopup listing={listing} />
            </Popup>
          </Marker>
        ))}
      </MarkerClusterGroup>
    </MapContainer>
  );
}

function ListingPopup({ listing }: { listing: Listing }) {
  const amenities = POPUP_AMENITIES.filter((k) => listing[k] === true).slice(0, 5);
  const thumb = listing.thumbnail_url ?? "/no-image.svg";
  const title = listing.title ?? "Tin cho thuê";

  return (
    <div className="text-[13px]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={thumb}
        alt={title}
        className="w-full h-32 object-cover bg-ink-700/10"
        loading="lazy"
        onError={(e) => {
          (e.currentTarget as HTMLImageElement).src = "/no-image.svg";
        }}
      />
      <div className="p-3">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-accent/10 text-accent">
            {propertyTypeLabel(listing.property_type)}
          </span>
          {listing.source_name ? (
            <span className="text-[10px] text-ink-400 uppercase">
              {listing.source_name}
            </span>
          ) : null}
        </div>
        <h3 className="font-semibold text-sm leading-snug line-clamp-2 mb-1.5 text-ink-900">
          {title}
        </h3>
        <div className="text-lg font-bold text-bad mb-1.5">
          {formatVNDFull(listing.price_vnd)}
          <span className="text-xs font-normal text-ink-500">/tháng</span>
        </div>
        <div className="text-xs text-ink-500 space-y-0.5 mb-2">
          <div>{locationLine(listing)}</div>
          <div className="flex gap-2 flex-wrap">
            {specChips(listing).map((chip, i) => (
              <span key={i}>{chip}</span>
            ))}
          </div>
        </div>
        {amenities.length !== 0 ? (
          <div className="flex flex-wrap gap-1 mb-2">
            {amenities.map((k) => (
              <span
                key={k as string}
                className="px-1.5 py-0.5 rounded bg-ink-900/5 text-[10px] text-ink-700"
              >
                {AMENITY_LABELS[k as string]}
              </span>
            ))}
          </div>
        ) : null}
        {listing.source_url ? (
          <a
            href={listing.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block w-full text-center bg-accent text-white py-2 rounded-lg text-sm font-semibold hover:bg-accent/90 transition-colors no-underline"
          >
            Xem tin gốc →
          </a>
        ) : null}
      </div>
    </div>
  );
}

function locationLine(listing: Listing): string {
  const ward = listing.ward ?? "—";
  const prov = listing.province ? `, ${listing.province}` : "";
  return `📍 ${ward}${prov}`;
}

function specChips(listing: Listing): string[] {
  const chips: string[] = [];
  if (listing.area_m2 != null) chips.push(`📐 ${listing.area_m2}m²`);
  if (listing.bedrooms != null) chips.push(`🛏 ${listing.bedrooms}PN`);
  if (listing.price_per_m2 != null) {
    chips.push(`≈ ${Math.round(listing.price_per_m2 / 1000)}k/m²`);
  }
  return chips;
}
