(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const money = (value, decimals = 2) =>
    `₹${new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value)}`;

  const number = (value, decimals = 2) =>
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value);

  const signedPercent = (value) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

  const compactMoney = (value) => {
    if (value >= 10000000) return `₹${(value / 10000000).toFixed(2)}Cr`;
    if (value >= 100000) return `₹${(value / 100000).toFixed(2)}L`;
    if (value >= 1000) return `₹${(value / 1000).toFixed(1)}K`;
    return `₹${value.toFixed(0)}`;
  };

  const chartTick = (value, usePrecision) => {
    if (value >= 100000) return `₹${(value / 100000).toFixed(usePrecision ? 3 : 2)}L`;
    if (value >= 1000) return `₹${(value / 1000).toFixed(1)}K`;
    return `₹${value.toFixed(0)}`;
  };

  /* ── Instruments & market data ────────────────────────────── */

  const instruments = [
    {
      ticker: "RELIANCE",
      name: "Reliance Industries",
      price: 2986.4,
      change: 1.86,
      logoClass: "logo-reliance",
      logoText: "R",
      exchange: "NSE",
      kind: "stock",
      keywords: "reliance industries oil telecom retail",
    },
    {
      ticker: "HDFCBANK",
      name: "HDFC Bank",
      price: 1712.3,
      change: 0.74,
      logoClass: "logo-hdfc",
      logoText: "H",
      exchange: "NSE",
      kind: "stock",
      keywords: "hdfc bank banking finance",
    },
    {
      ticker: "INFY",
      name: "Infosys",
      price: 1842.1,
      change: 1.12,
      logoClass: "logo-infy",
      logoText: "i",
      exchange: "NSE",
      kind: "stock",
      keywords: "infosys technology it software",
    },
    {
      ticker: "ZOMATO",
      name: "Zomato",
      price: 286.75,
      change: 2.42,
      logoClass: "logo-zomato",
      logoText: "z",
      exchange: "NSE",
      kind: "stock",
      keywords: "zomato food delivery quick commerce",
    },
    {
      ticker: "TATAMOTORS",
      name: "Tata Motors",
      price: 1004.55,
      change: 0.92,
      logoClass: "logo-tata",
      logoText: "T",
      exchange: "NSE",
      kind: "stock",
      keywords: "tata motors auto ev vehicles",
    },
    {
      ticker: "TCS",
      name: "Tata Consultancy Services",
      price: 4142.8,
      change: -0.58,
      logoClass: "logo-tcs",
      logoText: "TCS",
      exchange: "NSE",
      kind: "stock",
      keywords: "tcs technology it software",
    },
  ];

  const mostBoughtStocks = [
    instruments[0],
    instruments[3],
    instruments[1],
    instruments[4],
    instruments[2],
    instruments[5],
  ];

  const topGainers = [
    {
      ticker: "ADANIPORTS",
      name: "Adani Ports",
      price: 1412.65,
      change: 4.82,
      logoClass: "logo-adani",
      logoText: "A",
      exchange: "NSE",
      kind: "stock",
      keywords: "adani ports logistics infrastructure",
    },
    {
      ticker: "TRENT",
      name: "Trent",
      price: 6842.2,
      change: 3.94,
      logoClass: "logo-trent",
      logoText: "T",
      exchange: "NSE",
      kind: "stock",
      keywords: "trent retail tata",
    },
    {
      ticker: "BEL",
      name: "Bharat Electronics",
      price: 312.4,
      change: 3.67,
      logoClass: "logo-bel",
      logoText: "BEL",
      exchange: "NSE",
      kind: "stock",
      keywords: "bharat electronics defence",
    },
    {
      ticker: "JSWSTEEL",
      name: "JSW Steel",
      price: 1024.85,
      change: 3.21,
      logoClass: "logo-jsw",
      logoText: "JSW",
      exchange: "NSE",
      kind: "stock",
      keywords: "jsw steel metals",
    },
    {
      ticker: "TATAPOWER",
      name: "Tata Power",
      price: 428.9,
      change: 2.96,
      logoClass: "logo-tatapower",
      logoText: "TP",
      exchange: "NSE",
      kind: "stock",
      keywords: "tata power energy utilities",
    },
  ];

  instruments.push(...topGainers.slice(0, 3));

  const mostBoughtFunds = [
    {
      name: "HDFC Flexi Cap Fund",
      amc: "HDFC",
      amcMark: "H",
      amcClass: "logo-hdfc",
      category: "Flexi Cap",
      chipClass: "chip-violet",
      nav: 1842.5,
      returnValue: 24.8,
    },
    {
      name: "HDFC ELSS Tax Saver",
      amc: "HDFC",
      amcMark: "H",
      amcClass: "logo-hdfc",
      category: "ELSS",
      chipClass: "chip-amber",
      nav: 1218.9,
      returnValue: 19.4,
    },
    {
      name: "Nippon Nifty 50 Index",
      amc: "Nippon",
      amcMark: "N",
      amcClass: "logo-nippon",
      category: "Index",
      chipClass: "chip-green",
      nav: 248.75,
      returnValue: 15.2,
    },
    {
      name: "Parag Parikh Flexi Cap",
      amc: "PPFAS",
      amcMark: "P",
      amcClass: "logo-ppfas",
      category: "Flexi Cap",
      chipClass: "chip-violet",
      nav: 82.46,
      returnValue: 22.1,
    },
    {
      name: "ICICI Balanced Advantage",
      amc: "ICICI",
      amcMark: "I",
      amcClass: "logo-icici",
      category: "Hybrid",
      chipClass: "chip-cyan",
      nav: 68.92,
      returnValue: 13.7,
    },
  ];

  const topPerformingFunds = [
    {
      name: "Motilal Nasdaq 100 ETF",
      amc: "Motilal",
      amcMark: "M",
      amcClass: "logo-motilal",
      category: "Index ETF",
      chipClass: "chip-cyan",
      nav: 154.6,
      returnValue: 31.6,
    },
    {
      name: "HDFC Mid Cap Fund",
      amc: "HDFC",
      amcMark: "H",
      amcClass: "logo-hdfc",
      category: "Mid Cap",
      chipClass: "chip-violet",
      nav: 196.34,
      returnValue: 28.2,
    },
    {
      name: "Nippon Small Cap Fund",
      amc: "Nippon",
      amcMark: "N",
      amcClass: "logo-nippon",
      category: "Small Cap",
      chipClass: "chip-violet",
      nav: 142.78,
      returnValue: 26.9,
    },
    {
      name: "SBI Contra Fund",
      amc: "SBI",
      amcMark: "S",
      amcClass: "logo-sbi",
      category: "Contra",
      chipClass: "chip-cyan",
      nav: 392.15,
      returnValue: 24.4,
    },
    {
      name: "HDFC Gold ETF FoF",
      amc: "HDFC",
      amcMark: "H",
      amcClass: "logo-hdfc",
      category: "Gold",
      chipClass: "chip-amber",
      nav: 31.57,
      returnValue: 21.8,
    },
  ];

  const mostBookedFds = [
    {
      bank: "HDFC Bank",
      mark: "H",
      bankClass: "logo-hdfc",
      rate: 7.25,
      tenure: "1 – 2 years",
      minimum: "Min. ₹5,000",
    },
    {
      bank: "ICICI Bank",
      mark: "I",
      bankClass: "logo-icici",
      rate: 7.1,
      tenure: "15 – 18 months",
      minimum: "Min. ₹10,000",
    },
    {
      bank: "SBI",
      mark: "S",
      bankClass: "logo-sbi",
      rate: 7.0,
      tenure: "1 – 3 years",
      minimum: "Min. ₹1,000",
    },
    {
      bank: "Axis Bank",
      mark: "A",
      bankClass: "logo-axis",
      rate: 7.1,
      tenure: "18 – 24 months",
      minimum: "Min. ₹5,000",
    },
    {
      bank: "Kotak Mahindra",
      mark: "K",
      bankClass: "logo-kotak",
      rate: 7.15,
      tenure: "1 – 2 years",
      minimum: "Min. ₹5,000",
    },
  ];

  const highestRateFds = [
    {
      bank: "Bajaj Finance",
      mark: "B",
      bankClass: "logo-bajaj",
      rate: 8.15,
      tenure: "36 – 60 months",
      minimum: "Min. ₹15,000",
    },
    {
      bank: "Shriram Finance",
      mark: "S",
      bankClass: "logo-shriram",
      rate: 8.1,
      tenure: "36 – 60 months",
      minimum: "Min. ₹5,000",
    },
    {
      bank: "Ujjivan SFB",
      mark: "U",
      bankClass: "logo-ujjivan",
      rate: 8.0,
      tenure: "12 – 24 months",
      minimum: "Min. ₹1,000",
    },
    {
      bank: "HDFC Bank",
      mark: "H",
      bankClass: "logo-hdfc",
      rate: 7.25,
      tenure: "1 – 2 years",
      minimum: "Min. ₹5,000",
    },
    {
      bank: "IndusInd Bank",
      mark: "I",
      bankClass: "logo-indusind",
      rate: 7.25,
      tenure: "18 – 24 months",
      minimum: "Min. ₹5,000",
    },
  ];

  const searchData = [
    ...instruments.map((item) => ({
      ...item,
      type: "stock",
      typeLabel: "Stock",
      meta: `${item.ticker} · ${item.exchange}`,
    })),
    {
      id: "HDFC-FLEXI",
      name: "HDFC Flexi Cap Fund",
      meta: "Mutual fund · Direct plan",
      type: "fund",
      typeLabel: "Fund",
      logoClass: "logo-hdfc",
      logoText: "H",
      toast: "HDFC Flexi Cap Fund details opened",
    },
    {
      id: "HDFC-ELSS",
      name: "HDFC ELSS Tax Saver",
      meta: "Mutual fund · ELSS",
      type: "fund",
      typeLabel: "Fund",
      logoClass: "logo-hdfc",
      logoText: "H",
      toast: "HDFC ELSS Tax Saver details opened",
    },
    {
      id: "NIFTY-INDEX",
      name: "Nifty 50 Index Fund",
      meta: "Mutual fund · Index",
      type: "fund",
      typeLabel: "Fund",
      logoClass: "logo-nippon",
      logoText: "N",
      toast: "Nifty 50 Index Fund details opened",
    },
    {
      id: "NIFTY-BEES",
      name: "Nippon India Nifty BeES",
      meta: "ETF · NSE",
      type: "etf",
      typeLabel: "ETF",
      logoClass: "logo-nippon",
      logoText: "N",
      toast: "Nippon India Nifty BeES details opened",
    },
    {
      id: "NASDAQ-ETF",
      name: "Motilal Oswal Nasdaq 100 ETF",
      meta: "ETF · NSE",
      type: "etf",
      typeLabel: "ETF",
      logoClass: "logo-motilal",
      logoText: "M",
      toast: "Motilal Oswal Nasdaq 100 ETF details opened",
    },
    {
      id: "GOLD-ETF",
      name: "HDFC Gold ETF Fund of Fund",
      meta: "Mutual fund · Commodities",
      type: "fund",
      typeLabel: "Fund",
      logoClass: "logo-hdfc",
      logoText: "H",
      toast: "HDFC Gold ETF Fund of Fund details opened",
    },
  ];

  const periodData = {
    "1D": {
      values: [310640, 310920, 310780, 311150, 311040, 311420, 311350, 311680, 311590, 311860, 311780, 312050, 311950, 312480],
      labels: ["9:15 AM", "9:45 AM", "10:15 AM", "10:45 AM", "11:15 AM", "11:45 AM", "12:15 PM", "12:45 PM", "1:15 PM", "1:45 PM", "2:15 PM", "2:45 PM", "3:15 PM", "3:30 PM"],
      returnAmount: 1840,
      returnPct: 0.59,
      copy: "returns today",
    },
    "1W": {
      values: [308260, 309010, 308540, 309380, 308970, 309760, 309480, 310270, 309910, 310840, 310650, 311420, 311060, 312480],
      labels: ["Mon, 28 Oct", "Mon, 12:00", "Tue, 29 Oct", "Tue, 12:00", "Wed, 30 Oct", "Wed, 12:00", "Thu, 31 Oct", "Thu, 12:00", "Fri, 1 Nov", "Fri, 12:00", "Mon, 2 Nov", "Mon, 12:00", "Tue, 3 Nov", "Now"],
      returnAmount: 4220,
      returnPct: 1.37,
      copy: "returns this week",
    },
    "1M": {
      values: [300810, 302340, 301450, 303120, 302680, 304470, 303910, 305780, 304960, 307120, 306480, 308760, 307940, 312480],
      labels: ["6 Oct", "8 Oct", "10 Oct", "12 Oct", "14 Oct", "16 Oct", "18 Oct", "20 Oct", "22 Oct", "24 Oct", "26 Oct", "29 Oct", "1 Nov", "3 Nov"],
      returnAmount: 11670,
      returnPct: 3.88,
      copy: "returns this month",
    },
    "1Y": {
      values: [274850, 279640, 285120, 281760, 289430, 294180, 291560, 299780, 304220, 301560, 307840, 305290, 309640, 312480],
      labels: ["Nov 25", "Dec 25", "Jan 26", "Feb 26", "Mar 26", "Apr 26", "May 26", "Jun 26", "Jul 26", "Aug 26", "Sep 26", "Oct 26", "Oct 26", "Nov 26"],
      returnAmount: 37630,
      returnPct: 13.65,
      copy: "returns in the last year",
    },
    ALL: {
      values: [170000, 186400, 179800, 205600, 231900, 218400, 248700, 264300, 251800, 279600, 291300, 286700, 304800, 312480],
      labels: ["2019", "2020", "2020", "2021", "2021", "2022", "2022", "2023", "2023", "2024", "2024", "2025", "2026", "Now"],
      returnAmount: 142480,
      returnPct: 83.8,
      copy: "returns since inception",
    },
  };

  const logoMarkup = (item, extraClass = "") =>
    `<span class="company-logo ${item.logoClass} ${extraClass}" aria-hidden="true">${item.logoText}</span>`;

  /* ── Sparklines ───────────────────────────────────────────── */

  const sparkValues = {
    nifty: [23940, 24120, 24030, 24280, 24190, 24460, 24370, 24540, 24480, 24710, 24640, 24812],
    sensex: [79750, 80210, 79940, 80680, 80320, 81050, 80760, 81420],
    nasdaq: [19120, 19070, 19095, 19020, 19060, 18990, 19010, 18950, 18980, 18940, 18938],
  };

  function smoothPath(points) {
    if (!points.length) return "";
    let path = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
    for (let index = 1; index < points.length; index += 1) {
      const previous = points[index - 1];
      const current = points[index];
      const midX = (previous.x + current.x) / 2;
      path += ` C ${midX.toFixed(2)} ${previous.y.toFixed(2)}, ${midX.toFixed(2)} ${current.y.toFixed(2)}, ${current.x.toFixed(2)} ${current.y.toFixed(2)}`;
    }
    return path;
  }

  function drawSparkline(element, values, color, id) {
    if (!element) return;
    const width = 112;
    const height = 42;
    const paddingX = 2;
    const paddingY = 4;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const points = values.map((value, index) => ({
      x: paddingX + (index / (values.length - 1)) * (width - paddingX * 2),
      y: paddingY + ((max - value) / range) * (height - paddingY * 2),
    }));
    const line = smoothPath(points);
    const area = `${line} L ${points[points.length - 1].x.toFixed(2)} ${height - paddingY} L ${points[0].x.toFixed(2)} ${height - paddingY} Z`;

    element.innerHTML = `
      <defs>
        <linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.18"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path class="spark-area" d="${area}" fill="url(#${id})"/>
      <path class="spark-line" d="${line}" stroke="${color}" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${points[points.length - 1].x.toFixed(2)}" cy="${points[points.length - 1].y.toFixed(2)}" r="1.9" fill="${color}" stroke="#fff" stroke-width="1.2"/>
    `;
  }

  drawSparkline($("#sparkNifty"), sparkValues.nifty, "#00b386", "niftyGradient");
  drawSparkline($("#sparkSensex"), sparkValues.sensex, "#00b386", "sensexGradient");
  drawSparkline($("#sparkNasdaq"), sparkValues.nasdaq, "#eb5757", "nasdaqGradient");

  /* ── Market discovery panels ──────────────────────────────── */

  const stockCard = (item) => {
    const positive = item.change >= 0;
    return `
      <button class="quote-card" type="button" data-instrument="${item.ticker}" aria-label="${item.name}, ${money(item.price)}, ${signedPercent(item.change)}">
        <div class="quote-card-head">
          ${logoMarkup(item)}
          <span class="quote-card-copy">
            <strong>${item.ticker}</strong>
            <span>${item.name}</span>
          </span>
        </div>
        <div class="quote-card-bottom">
          <span class="quote-price">${money(item.price)}</span>
          <span class="quote-change ${positive ? "positive" : "negative"}">${signedPercent(item.change)}</span>
        </div>
      </button>
    `;
  };

  const gainerCard = (item) => {
    const positive = item.change >= 0;
    return `
      <button class="gainer-card" type="button" data-instrument="${item.ticker}" aria-label="${item.name}, ${money(item.price)}, ${signedPercent(item.change)}">
        ${logoMarkup(item)}
        <span class="gainer-copy">
          <strong>${item.ticker}</strong>
          <span>${item.name}</span>
        </span>
        <span class="gainer-right">
          <strong>${money(item.price)}</strong>
          <span class="${positive ? "" : "negative"}">${signedPercent(item.change)}</span>
        </span>
      </button>
    `;
  };

  const fundCard = (item) => `
    <button class="fund-card" type="button" data-toast="${item.name} details opened">
      <div class="fund-card-top">
        <span class="fund-badge ${item.amcClass}" aria-hidden="true">${item.amcMark}</span>
        <span class="category-chip ${item.chipClass}">${item.category}</span>
      </div>
      <h4>${item.name}</h4>
      <div class="fund-card-bottom">
        <span>NAV ${money(item.nav)}</span>
        <strong>+${item.returnValue.toFixed(1)}% 1Y</strong>
      </div>
    </button>
  `;

  const fdCard = (item) => `
    <button class="fd-card" type="button" data-toast="${item.bank} FD booking opened">
      <div class="fd-card-top">
        <span class="fd-bank">
          <span class="fund-badge ${item.bankClass}" aria-hidden="true">${item.mark}</span>
          <span class="fd-bank-copy">
            <strong>${item.bank}</strong>
            <span>${item.tenure}</span>
          </span>
        </span>
        <span class="fd-rate">${item.rate.toFixed(2)}<span>% p.a.</span></span>
      </div>
      <div class="fd-card-bottom">
        <span>${item.minimum}</span>
        <strong>Book FD →</strong>
      </div>
    </button>
  `;

  const sectionMarkup = ({ key, title, subtitle, itemMarkup }) => `
    <div class="quote-section">
      <div class="section-row">
        <div class="section-title">
          <h3>${title}</h3>
          <span>${subtitle}</span>
        </div>
        <div class="section-actions">
          <button class="text-link" type="button" data-toast="Viewing all ${title.toLowerCase()}">View all</button>
          <div class="carousel-nav" aria-label="${title} carousel controls">
            <button class="carousel-arrow" type="button" data-carousel-target="${key}" data-dir="-1" aria-label="Previous ${title}">
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m12.5 4.5-5 5.5 5 5.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
            <button class="carousel-arrow" type="button" data-carousel-target="${key}" data-dir="1" aria-label="Next ${title}">
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m7.5 4.5 5 5.5-5 5.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </div>
        </div>
      </div>
      <div class="carousel">
        <div class="carousel-track" id="${key}" tabindex="0" aria-label="${title}">
          ${itemMarkup}
        </div>
      </div>
    </div>
  `;

  const marketPanels = [
    {
      key: "stocks",
      label: "Stocks",
      primary: {
        key: "stocksMostBought",
        title: "Most bought",
        subtitle: "Popular with investors today",
        items: mostBoughtStocks.map(stockCard).join(""),
      },
      secondary: {
        key: "stocksTopGainers",
        title: "Top gainers",
        subtitle: "NSE · Live",
        items: topGainers.map(gainerCard).join(""),
      },
    },
    {
      key: "mutualFunds",
      label: "Mutual Funds",
      primary: {
        key: "fundsMostBought",
        title: "Most bought",
        subtitle: "Direct plans · Zero commission",
        items: mostBoughtFunds.map(fundCard).join(""),
      },
      secondary: {
        key: "fundsTopPerformers",
        title: "Top performers",
        subtitle: "1 year returns",
        items: topPerformingFunds.map(fundCard).join(""),
      },
    },
    {
      key: "fixedDeposits",
      label: "Fixed Deposits",
      primary: {
        key: "fdsMostBooked",
        title: "Most booked",
        subtitle: "Trusted bank FDs",
        items: mostBookedFds.map(fdCard).join(""),
      },
      secondary: {
        key: "fdsHighestRates",
        title: "Highest rates",
        subtitle: "Corporate & bank FDs",
        items: highestRateFds.map(fdCard).join(""),
      },
    },
  ];

  $("#marketPanels").innerHTML = marketPanels
    .map(
      (panel, index) => `
        <div class="market-panel ${index === 0 ? "is-active" : ""}" data-market-panel="${panel.key}" role="tabpanel" aria-label="${panel.label}">
          ${sectionMarkup({ ...panel.primary, itemMarkup: panel.primary.items })}
          <div class="section-divider"></div>
          ${sectionMarkup({ ...panel.secondary, itemMarkup: panel.secondary.items })}
        </div>
      `,
    )
    .join("");

  /* ── Carousels ────────────────────────────────────────────── */

  function updateCarouselArrows(targetId) {
    const track = document.getElementById(targetId);
    if (!track) return;
    const section = track.closest(".quote-section");
    if (!section) return;
    const previous = $('[data-carousel-target="' + targetId + '"][data-dir="-1"]', section);
    const next = $('[data-carousel-target="' + targetId + '"][data-dir="1"]', section);
    if (!previous || !next) return;
    if (!track.clientWidth) return;
    previous.disabled = track.scrollLeft <= 1;
    next.disabled = track.scrollLeft + track.clientWidth >= track.scrollWidth - 2;
  }

  function refreshVisibleCarousels() {
    $$(".carousel-track").forEach((track) => {
      const panel = track.closest(".market-panel");
      if (panel && !panel.classList.contains("is-active")) return;
      updateCarouselArrows(track.id);
    });
  }

  $$(".carousel-track").forEach((track) => {
    track.addEventListener("scroll", () => updateCarouselArrows(track.id), { passive: true });
    track.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      event.preventDefault();
      track.scrollBy({ left: (event.key === "ArrowRight" ? 1 : -1) * track.clientWidth * 0.72, behavior: "smooth" });
    });
  });

  document.addEventListener("click", (event) => {
    const arrow = event.target.closest(".carousel-arrow");
    if (!arrow || arrow.disabled) return;
    const track = document.getElementById(arrow.dataset.carouselTarget);
    if (!track) return;
    track.scrollBy({ left: Number(arrow.dataset.dir) * track.clientWidth * 0.78, behavior: "smooth" });
    window.setTimeout(() => updateCarouselArrows(track.id), 360);
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(window.__carouselResizeTimer);
    window.__carouselResizeTimer = window.setTimeout(refreshVisibleCarousels, 120);
  });

  requestAnimationFrame(() => {
    refreshVisibleCarousels();
    $$(".carousel-track").forEach((track) => {
      track.scrollLeft = 0;
    });
  });

  /* ── Market tabs ──────────────────────────────────────────── */

  function selectMarketTab(key) {
    $$(".market-tab").forEach((tab) => {
      const active = tab.dataset.marketTab === key;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    $$(".market-panel").forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.marketPanel === key);
    });
    requestAnimationFrame(refreshVisibleCarousels);
  }

  $$(".market-tab").forEach((tab) => {
    tab.addEventListener("click", () => selectMarketTab(tab.dataset.marketTab));
  });

  /* ── Portfolio chart ──────────────────────────────────────── */

  const chartSvg = $("#portfolioChart");
  const chartWrap = $("#chartWrap");
  const chartTooltip = $("#chartTooltip");
  const chartTooltipDate = $("#chartTooltipDate");
  const chartTooltipValue = $("#chartTooltipValue");
  let activePeriod = "1Y";
  let chartGeometry = null;
  let chartAnimationFrame = null;

  function renderChart(period, animate = true) {
    const data = periodData[period];
    if (!data || !chartSvg || !chartWrap) return;
    activePeriod = period;

    const width = Math.max(320, chartWrap.clientWidth);
    const height = Math.max(128, chartWrap.clientHeight);
    const padding = { left: 3, right: 57, top: 12, bottom: 21 };
    const values = data.values;
    const lowest = Math.min(...values);
    const highest = Math.max(...values);
    const expansion = (highest - lowest || highest * 0.01) * 0.18;
    const min = lowest - expansion * 0.55;
    const max = highest + expansion;
    const range = max - min;
    const usePrecision = (highest - lowest) / highest < 0.03;

    const xFor = (index) =>
      padding.left + (index / (values.length - 1)) * (width - padding.left - padding.right);
    const yFor = (value) =>
      padding.top + ((max - value) / range) * (height - padding.top - padding.bottom);

    const points = values.map((value, index) => ({ x: xFor(index), y: yFor(value) }));
    const linePath = smoothPath(points);
    const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(2)} ${(height - padding.bottom).toFixed(2)} L ${points[0].x.toFixed(2)} ${(height - padding.bottom).toFixed(2)} Z`;

    const gridLines = [];
    const tickCount = 4;
    for (let index = 0; index < tickCount; index += 1) {
      const ratio = index / (tickCount - 1);
      const value = max - ratio * (max - min);
      const y = yFor(value);
      gridLines.push(`
        <line class="chart-grid-line" x1="${padding.left}" y1="${y.toFixed(2)}" x2="${(width - padding.right).toFixed(2)}" y2="${y.toFixed(2)}"/>
        <text class="chart-axis-label" x="${(width - padding.right + 7).toFixed(2)}" y="${(y + 2.8).toFixed(2)}" text-anchor="start">${chartTick(value, usePrecision)}</text>
      `);
    }

    const firstLabel = data.labels[0];
    const middleLabel = data.labels[Math.floor((data.labels.length - 1) / 2)];
    const lastLabel = data.labels[data.labels.length - 1];
    const xLabels = `
      <text class="chart-axis-label" x="${padding.left}" y="${height - 4}" text-anchor="start">${firstLabel}</text>
      <text class="chart-axis-label" x="${(width - padding.right) / 2}" y="${height - 4}" text-anchor="middle">${middleLabel}</text>
      <text class="chart-axis-label" x="${width - padding.right}" y="${height - 4}" text-anchor="end">${lastLabel}</text>
    `;

    const lastPoint = points[points.length - 1];

    chartSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    chartSvg.innerHTML = `
      <defs>
        <linearGradient id="chartAreaGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#00b386" stop-opacity="0.17"/>
          <stop offset="65%" stop-color="#00b386" stop-opacity="0.05"/>
          <stop offset="100%" stop-color="#00b386" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <g>${gridLines.join("")}</g>
      <g>${xLabels}</g>
      <path class="chart-area" d="${areaPath}" fill="url(#chartAreaGradient)"/>
      <path class="chart-line" d="${linePath}"/>
      <circle cx="${lastPoint.x.toFixed(2)}" cy="${lastPoint.y.toFixed(2)}" r="7.5" fill="rgba(0, 179, 134, 0.10)"/>
      <circle cx="${lastPoint.x.toFixed(2)}" cy="${lastPoint.y.toFixed(2)}" r="3.2" fill="#00b386" stroke="#fff" stroke-width="1.7"/>
      <g id="chartFocus" visibility="hidden">
        <line class="chart-hover-line" y1="${padding.top}" y2="${height - padding.bottom}"/>
        <circle class="chart-hover-dot" r="3.6"/>
      </g>
      <rect id="chartHitArea" x="${padding.left}" y="0" width="${width - padding.left - padding.right}" height="${height}" fill="transparent" style="cursor: crosshair"/>
    `;

    chartGeometry = { width, height, padding, points, data, xFor, yFor };

    const line = $(".chart-line", chartSvg);
    const area = $(".chart-area", chartSvg);
    if (animate && line) {
      const length = line.getTotalLength();
      line.style.strokeDasharray = `${length}`;
      line.style.strokeDashoffset = `${length}`;
      area.style.opacity = "0";
      window.requestAnimationFrame(() => {
        line.style.transition = "stroke-dashoffset 600ms cubic-bezier(0.25, 0.7, 0.25, 1)";
        line.style.strokeDashoffset = "0";
        area.style.transition = "opacity 500ms ease 90ms";
        area.style.opacity = "1";
      });
    }

    const hitArea = $("#chartHitArea", chartSvg);
    if (hitArea) {
      hitArea.addEventListener("pointermove", (event) => handleChartPointer(event));
      hitArea.addEventListener("pointerleave", hideChartHover);
    }

    chartSvg.setAttribute("aria-label", `Portfolio value over ${period === "ALL" ? "all time" : `the last ${period}`}, current value ₹3,12,480`);
    hideChartHover();
  }

  function handleChartPointer(event) {
    if (!chartGeometry) return;
    const bounds = chartSvg.getBoundingClientRect();
    const localX = event.clientX - bounds.left;
    const { points, data, padding } = chartGeometry;

    let closestIndex = 0;
    let closestDistance = Infinity;
    points.forEach((point, index) => {
      const distance = Math.abs(point.x - localX);
      if (distance < closestDistance) {
        closestDistance = distance;
        closestIndex = index;
      }
    });

    const point = points[closestIndex];
    const focus = $("#chartFocus", chartSvg);
    const hoverLine = $(".chart-hover-line", chartSvg);
    const hoverDot = $(".chart-hover-dot", chartSvg);
    if (!focus || !hoverLine || !hoverDot) return;

    focus.setAttribute("visibility", "visible");
    hoverLine.setAttribute("x1", point.x.toFixed(2));
    hoverLine.setAttribute("x2", point.x.toFixed(2));
    hoverLine.setAttribute("y1", padding.top.toFixed(2));
    hoverLine.setAttribute("y2", (chartGeometry.height - padding.bottom).toFixed(2));
    hoverDot.setAttribute("cx", point.x.toFixed(2));
    hoverDot.setAttribute("cy", point.y.toFixed(2));

    chartTooltipDate.textContent = data.labels[closestIndex];
    chartTooltipValue.textContent = money(data.values[closestIndex], 0);
    chartTooltip.hidden = false;
    const tooltipX = Math.min(Math.max(point.x, 48), chartGeometry.width - 48);
    const tooltipY = Math.max(point.y - 7, 36);
    chartTooltip.style.left = `${tooltipX}px`;
    chartTooltip.style.top = `${tooltipY}px`;
  }

  function hideChartHover() {
    const focus = $("#chartFocus", chartSvg);
    if (focus) focus.setAttribute("visibility", "hidden");
    if (chartTooltip) chartTooltip.hidden = true;
  }

  function updatePeriodSummary(period) {
    const data = periodData[period];
    const pill = $("#periodReturnPill");
    const amount = $("#periodReturnAmount");
    const copy = $("#periodReturnCopy");
    const positive = data.returnPct >= 0;
    pill.textContent = `${positive ? "+" : ""}${data.returnPct.toFixed(2)}%`;
    pill.classList.toggle("positive", positive);
    pill.classList.toggle("negative", !positive);
    amount.textContent = `${positive ? "+" : "−"}${money(Math.abs(data.returnAmount), 0)}`;
    amount.classList.toggle("positive-text", positive);
    amount.classList.toggle("negative-text", !positive);
    copy.textContent = data.copy;
  }

  function selectPeriod(period) {
    $$(".timeline-tab").forEach((tab) => {
      const active = tab.dataset.period === period;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    updatePeriodSummary(period);
    renderChart(period, true);
  }

  $$(".timeline-tab").forEach((tab) => {
    tab.addEventListener("click", () => selectPeriod(tab.dataset.period));
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(window.__chartResizeTimer);
    window.__chartResizeTimer = window.setTimeout(() => renderChart(activePeriod, false), 130);
  });

  $("#refreshChart")?.addEventListener("click", (event) => {
    const button = event.currentTarget;
    button.classList.add("is-spinning");
    renderChart(activePeriod, true);
    showToast("Portfolio value refreshed");
    window.setTimeout(() => button.classList.remove("is-spinning"), 650);
  });

  requestAnimationFrame(() => {
    updatePeriodSummary(activePeriod);
    renderChart(activePeriod, false);
  });

  /* ── Search with keyboard autocomplete ────────────────────── */

  const searchShell = $("#searchShell");
  const searchInput = $("#globalSearch");
  const searchPopover = $("#searchPopover");
  const searchResults = $("#searchResults");
  const searchTitle = $("#searchPopoverTitle");
  let searchMatches = [];
  let highlightedIndex = 0;

  function getSearchMatches(query) {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return searchData.slice(0, 6);
    return searchData
      .filter((item) =>
        `${item.name} ${item.meta} ${item.typeLabel} ${item.keywords || ""}`.toLowerCase().includes(normalized),
      )
      .slice(0, 7);
  }

  function renderSearchResults(query = "") {
    searchMatches = getSearchMatches(query);
    searchTitle.textContent = query.trim() ? "Search results" : "Trending on Groww";
    if (!searchMatches.length) {
      searchResults.innerHTML = `
        <div class="search-empty">
          <strong>No matches for “${escapeHtml(query.trim())}”</strong>
          Try a stock name, ticker, mutual fund, or ETF.
        </div>
      `;
      return;
    }

    highlightedIndex = Math.min(highlightedIndex, searchMatches.length - 1);
    searchResults.innerHTML = searchMatches
      .map((item, index) => `
        <button class="search-result ${index === highlightedIndex ? "is-highlighted" : ""}" type="button" role="option" aria-selected="${index === highlightedIndex}" data-search-id="${item.id || item.ticker}">
          ${logoMarkup(item)}
          <span class="search-result-copy">
            <strong>${item.name}</strong>
            <span>${item.meta || `${item.ticker} · ${item.exchange}`}</span>
          </span>
          <span class="search-result-type ${item.type}">${item.typeLabel}</span>
          <svg class="search-result-arrow" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m7.5 4.5 5 5.5-5 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      `)
      .join("");
  }

  function openSearch() {
    renderSearchResults(searchInput.value);
    searchPopover.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
  }

  function closeSearch() {
    searchPopover.hidden = true;
    searchInput.setAttribute("aria-expanded", "false");
  }

  function chooseSearchResult(item) {
    if (!item) return;
    if (item.type === "stock") {
      const instrument = instruments.find((candidate) => candidate.ticker === item.ticker);
      if (instrument) selectInstrument(instrument);
      showToast(`${item.ticker} loaded in Quick invest`);
    } else {
      showToast(item.toast || `${item.name} details opened`);
    }
    searchInput.value = "";
    closeSearch();
    searchInput.blur();
  }

  function highlightSearchResult(index) {
    if (!searchMatches.length) return;
    highlightedIndex = (index + searchMatches.length) % searchMatches.length;
    const options = $$(".search-result", searchResults);
    options.forEach((option, optionIndex) => {
      const highlighted = optionIndex === highlightedIndex;
      option.classList.toggle("is-highlighted", highlighted);
      option.setAttribute("aria-selected", String(highlighted));
      if (highlighted) option.scrollIntoView({ block: "nearest" });
    });
  }

  searchInput.addEventListener("focus", openSearch);
  searchInput.addEventListener("input", () => {
    highlightedIndex = 0;
    openSearch();
  });

  searchResults.addEventListener("click", (event) => {
    const option = event.target.closest(".search-result");
    if (!option) return;
    const item = searchData.find((candidate) => (candidate.id || candidate.ticker) === option.dataset.searchId);
    chooseSearchResult(item);
  });

  searchResults.addEventListener("pointermove", (event) => {
    const option = event.target.closest(".search-result");
    if (!option) return;
    const index = $$(".search-result", searchResults).indexOf(option);
    if (index >= 0 && index !== highlightedIndex) highlightSearchResult(index);
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
      openSearch();
      return;
    }

    if (searchPopover.hidden) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlightSearchResult(highlightedIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlightSearchResult(highlightedIndex - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      chooseSearchResult(searchMatches[highlightedIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeSearch();
      searchInput.blur();
    }
  });

  /* ── Popovers ─────────────────────────────────────────────── */

  function closeAllPopovers(except) {
    [
      ["#notificationsPopover", "#notificationsBtn"],
      ["#profilePopover", "#profileBtn"],
    ].forEach(([popoverSelector, buttonSelector]) => {
      const popover = $(popoverSelector);
      const button = $(buttonSelector);
      if (!popover || popover === except) return;
      popover.hidden = true;
      button?.setAttribute("aria-expanded", "false");
    });
  }

  $("#notificationsBtn")?.addEventListener("click", () => {
    const popover = $("#notificationsPopover");
    const willOpen = popover.hidden;
    closeAllPopovers(popover);
    popover.hidden = !willOpen;
    $("#notificationsBtn").setAttribute("aria-expanded", String(willOpen));
  });

  $("#profileBtn")?.addEventListener("click", () => {
    const popover = $("#profilePopover");
    const willOpen = popover.hidden;
    closeAllPopovers(popover);
    popover.hidden = !willOpen;
    $("#profileBtn").setAttribute("aria-expanded", String(willOpen));
  });

  $("#walletChip")?.addEventListener("click", () => {
    closeAllPopovers();
    showToast("Add funds flow opened · Wallet balance ₹12,450");
  });

  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".popover-anchor")) closeAllPopovers();
    if (!event.target.closest("#searchShell")) closeSearch();
  });

  /* ── Order ticket ─────────────────────────────────────────── */

  const stockPicker = $("#stockPicker");
  const stockMenu = $("#stockMenu");
  const limitPriceInput = $("#limitPrice");
  const quantityInput = $("#quantity");
  const estimatedAmount = $("#estimatedAmount");
  const placeOrder = $("#placeOrder");
  const placeOrderLabel = $("#placeOrderLabel");
  const productBadge = $("#productBadge");
  let selectedInstrument = instruments[0];
  let tradeSide = "buy";
  let orderMode = "intraday";
  let orderSuccessTimer = null;

  function renderStockMenu() {
    if (!stockMenu) return;
    stockMenu.innerHTML = instruments
      .map(
        (item) => `
          <button class="stock-menu-option" type="button" role="option" data-ticker="${item.ticker}" aria-selected="${item.ticker === selectedInstrument.ticker}">
            ${logoMarkup(item)}
            <div>
              <strong>${item.ticker}</strong>
              <span>${item.name} · NSE</span>
            </div>
            <span class="menu-price">${money(item.price)}</span>
          </button>
        `,
      )
      .join("");
  }

  function updateOrderButton() {
    const quantity = Math.max(0, Number(quantityInput.value) || 0);
    placeOrderLabel.textContent = `${tradeSide === "buy" ? "Buy" : "Sell"} ${selectedInstrument.ticker}${quantity ? ` · ${quantity}` : ""}`;
    placeOrder.classList.toggle("is-sell", tradeSide === "sell");
  }

  function updateEstimate() {
    const price = Math.max(0, Number(limitPriceInput.value) || 0);
    const quantity = Math.max(0, Math.floor(Number(quantityInput.value) || 0));
    estimatedAmount.textContent = money(price * quantity);
    updateOrderButton();
  }

  function selectInstrument(item) {
    selectedInstrument = item;
    const logo = $("#selectedLogo");
    logo.className = `company-logo ${item.logoClass}`;
    logo.textContent = item.logoText;
    $("#selectedTicker").textContent = item.ticker;
    $("#selectedName").textContent = item.name;
    $("#selectedPrice").textContent = money(item.price);
    const change = $("#selectedChange");
    change.textContent = signedPercent(item.change);
    change.className = item.change >= 0 ? "positive-text" : "negative-text";
    limitPriceInput.value = item.price.toFixed(2);
    updateEstimate();
    renderStockMenu();
    closeStockMenu();
  }

  function openStockMenu() {
    stockMenu.hidden = false;
    stockPicker.setAttribute("aria-expanded", "true");
  }

  function closeStockMenu() {
    stockMenu.hidden = true;
    stockPicker.setAttribute("aria-expanded", "false");
  }

  stockPicker?.addEventListener("click", () => {
    if (stockMenu.hidden) openStockMenu();
    else closeStockMenu();
  });

  stockMenu?.addEventListener("click", (event) => {
    const option = event.target.closest(".stock-menu-option");
    if (!option) return;
    const instrument = instruments.find((item) => item.ticker === option.dataset.ticker);
    if (instrument) {
      selectInstrument(instrument);
      showToast(`${instrument.ticker} selected`);
    }
  });

  $$(".trade-side .segment").forEach((segment) => {
    segment.addEventListener("click", () => {
      tradeSide = segment.dataset.side;
      $$(".trade-side .segment").forEach((candidate) => {
        const active = candidate === segment;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-selected", String(active));
      });
      updateOrderButton();
    });
  });

  $$(".mode-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      orderMode = tab.dataset.mode;
      $$(".mode-tab").forEach((candidate) => {
        const active = candidate === tab;
        candidate.classList.toggle("is-active", active);
        candidate.setAttribute("aria-selected", String(active));
      });
      productBadge.textContent = orderMode === "intraday" ? "MIS" : "CNC";
    });
  });

  [limitPriceInput, quantityInput].forEach((input) => {
    input?.addEventListener("input", updateEstimate);
    input?.addEventListener("blur", () => {
      if (input === quantityInput) {
        input.value = String(Math.max(1, Math.floor(Number(input.value) || 1)));
        updateEstimate();
      }
    });
  });

  placeOrder?.addEventListener("click", () => {
    const price = Number(limitPriceInput.value);
    const quantity = Math.floor(Number(quantityInput.value));
    if (!price || price <= 0 || !quantity || quantity <= 0) {
      showToast("Enter a valid limit price and quantity");
      return;
    }

    window.clearTimeout(orderSuccessTimer);
    placeOrder.classList.add("is-success");
    placeOrderLabel.textContent = `${tradeSide === "buy" ? "Buy" : "Sell"} order placed · ${quantity} ${selectedInstrument.ticker}`;
    showToast(
      `${tradeSide === "buy" ? "Buy" : "Sell"} order placed for ${quantity} ${selectedInstrument.ticker} at ${money(price)} (simulated)`,
    );
    orderSuccessTimer = window.setTimeout(() => {
      placeOrder.classList.remove("is-success");
      updateOrderButton();
    }, 2600);
  });

  renderStockMenu();
  selectInstrument(instruments[0]);
  updateEstimate();

  /* ── SIP toggles ──────────────────────────────────────────── */

  function updateSipSummary() {
    const items = $$(".sip-item");
    let activeCount = 0;
    let total = 0;
    items.forEach((item) => {
      const toggle = $('input[type="checkbox"]', item);
      if (toggle?.checked) {
        activeCount += 1;
        total += Number(item.dataset.amount);
      }
    });
    const label = `${activeCount} auto-debit${activeCount === 1 ? "" : "s"}`;
    $("#sipSummaryText").innerHTML = `<strong>${label}</strong> · ${money(total, 0)} due this week`;
  }

  $$(".sip-item").forEach((item) => {
    const toggle = $('input[type="checkbox"]', item);
    const status = $(".auto-status", item);
    toggle?.addEventListener("change", () => {
      const fundName = $(".sip-info strong", item).textContent;
      if (toggle.checked) {
        status.textContent = "Auto-debit on";
        status.classList.remove("is-paused");
        showToast(`Auto-debit turned on for ${fundName}`);
      } else {
        status.textContent = "Auto-debit paused";
        status.classList.add("is-paused");
        showToast(`Auto-debit paused for ${fundName}`);
      }
      updateSipSummary();
    });
  });

  $("#manageSips")?.addEventListener("click", () => showToast("SIP management opened"));

  /* ── Navigation, links, toast ─────────────────────────────── */

  $$(".nav-link").forEach((link) => {
    link.addEventListener("click", () => {
      $$(".nav-link").forEach((candidate) => {
        const active = candidate === link;
        candidate.classList.toggle("is-active", active);
        if (active) candidate.setAttribute("aria-current", "page");
        else candidate.removeAttribute("aria-current");
      });

      const target = link.dataset.scrollTarget;
      if (target === "top") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else {
        document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-toast]");
    if (!trigger) return;
    showToast(trigger.dataset.toast);
  });

  let toastTimer = null;
  function showToast(message) {
    const toast = $("#toast");
    if (!toast) return;
    $("#toastText").textContent = message;
    toast.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2800);
  }

  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, (character) => {
      const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
      return entities[character];
    });
  }

  /* ── Keep the initial view sharp on font load ─────────────── */

  if (document.fonts?.ready) {
    document.fonts.ready.then(() => {
      refreshVisibleCarousels();
      renderChart(activePeriod, false);
    });
  }
})();
