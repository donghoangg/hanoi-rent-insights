"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Bản đồ" },
  { href: "/dashboard", label: "Phân tích" },
  { href: "/about", label: "Giới thiệu" },
];

export default function NavBar() {
  const pathname = usePathname();
  return (
    <header className="h-14 shrink-0 bg-ink-900 text-white flex items-center px-4 gap-6 z-[1100] relative">
      <Link href="/" className="flex items-center gap-2 font-bold text-lg">
        <span className="inline-block w-7 h-7 rounded-md bg-accent grid place-items-center text-sm">
          HR
        </span>
        HanoiRent <span className="text-accent-soft font-normal">Insights</span>
      </Link>
      <nav className="flex items-center gap-1 ml-2">
        {LINKS.map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                active
                  ? "bg-white/15 text-white"
                  : "text-ink-400 hover:text-white hover:bg-white/10"
              }`}
            >
              {l.label}
            </Link>
          );
        })}
      </nav>
      <div className="ml-auto text-xs text-ink-400 hidden sm:block">
        Dữ liệu thuê nhà Hà Nội · Nhatot + Mogi
      </div>
    </header>
  );
}
