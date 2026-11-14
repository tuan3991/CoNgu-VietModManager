/**
 * Lucide Steam & Gaming Extensions
 * CỔ NGỮ (VietModHub) - Bổ sung các icon Gaming phong cách Steam cho thư viện Lucide
 */
(function () {
  if (typeof window === "undefined" || !window.lucide) return;

  // Icon Steam chuẩn phong cách Lucide (stroke 2px, 24x24 viewBox)
  const SteamIcon = [
    ["path", { d: "M12 2a10 10 0 0 0-9.95 9.07l5.44 2.25a2.75 2.75 0 0 1 1.76-.32l2.5-3.62a3.75 3.75 0 1 1 5.25 4.88l-3.62 2.5a2.75 2.75 0 0 1-.32 1.76l2.25 5.44A10 10 0 1 0 12 2z" }],
    ["circle", { cx: "8.5", cy: "15.5", r: "1.75" }],
    ["circle", { cx: "15", cy: "10.25", r: "1.5" }]
  ];

  // Icon YouTube
  const YoutubeIcon = [
    ["path", { d: "M2.5 17a24.12 24.12 0 0 1 0-10 2 2 0 0 1 1.4-1.4 49.56 49.56 0 0 1 16.2 0A2 2 0 0 1 21.5 7a24.12 24.12 0 0 1 0 10 2 2 0 0 1-1.4 1.4 49.55 49.55 0 0 1-16.2 0A2 2 0 0 1 2.5 17" }],
    ["polygon", { points: "10 15 15 12 10 9 10 15" }]
  ];

  // Icon Epic Games
  const EpicIcon = [
    ["path", { d: "M12 2 4 5v12l8 5 8-5V5l-8-3z" }],
    ["path", { d: "M15 9h-6v6h6" }],
    ["line", { x1: "9", y1: "12", x2: "13", y2: "12" }]
  ];

  // Gán vào Lucide Icons
  if (window.lucide.icons) {
    window.lucide.icons.Steam = SteamIcon;
    window.lucide.icons.steam = SteamIcon;
    window.lucide.icons.Youtube = YoutubeIcon;
    window.lucide.icons.youtube = YoutubeIcon;
    window.lucide.icons.Epic = EpicIcon;
    window.lucide.icons.epic = EpicIcon;
  }
  window.lucide.Steam = SteamIcon;
  window.lucide.Youtube = YoutubeIcon;
  window.lucide.Epic = EpicIcon;
})();
