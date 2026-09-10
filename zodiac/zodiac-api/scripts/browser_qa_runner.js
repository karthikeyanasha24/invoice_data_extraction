(function () {
  if (window.__uiQaProgress && window.__uiQaProgress.status === "running") {
    return "already running";
  }

  const tests = [
    { id: "rank_top3_countries", question: "Top 3 countries by billed revenue", new_thread: true },
    { id: "rank_lowest_customer_2004", question: "Which customer had the lowest sales in 2004?", new_thread: true },
    { id: "rank_top10_products_2005", question: "Top 10 products by revenue in 2005", new_thread: true },
    { id: "rank_top5_invoice_count", question: "Show the five biggest customers by invoice count", new_thread: true },
    { id: "rank_top_industry", question: "Which industry generated the most revenue?", new_thread: true },
    { id: "time_compare_years", question: "Compare sales in 2004 and 2005", new_thread: true },
    { id: "time_monthly_2004", question: "Show monthly sales for 2004", new_thread: true },
    { id: "time_total_2003", question: "What were total billed sales in 2003?", new_thread: true },
    { id: "time_quarterly", question: "Sales trend by quarter", new_thread: true },
    { id: "filter_negative_2005", question: "Show negative billing documents in 2005", new_thread: true },
    { id: "filter_germany_customers", question: "List all customers in Germany", new_thread: true },
    { id: "filter_customer_docs", question: "Show billing documents for customer 0000045000", new_thread: true },
    { id: "filter_zero_qty", question: "Materials with zero billed quantity", new_thread: true },
    { id: "filter_industry_chemicals", question: "Show sales for industry Chemicals", new_thread: true },
    { id: "list_material_names", question: "List all material names", new_thread: true },
    { id: "list_vendor_names", question: "Show vendor names", new_thread: true },
    { id: "count_customers", question: "How many customers do we have?", new_thread: true },
    { id: "count_sales_orders", question: "How many sales orders are there?", new_thread: true },
    { id: "multidim_country_industry", question: "Which country and industry combination has the highest sales?", new_thread: true },
    { id: "multidim_top5_with_dims", question: "Top 5 customers by sales with country and industry", new_thread: true },
    { id: "multidim_revenue_filter", question: "Show customers, countries, and industries with revenue above 1 million", new_thread: true },
    { id: "profit_gross_by_product", question: "What is gross margin by product?", new_thread: true },
    { id: "profit_lowest_margins", question: "Which products have the lowest margins?", new_thread: true },
    { id: "profit_net_by_customer", question: "Show net profit by customer", new_thread: true },
    { id: "followup_us_a", question: "Top 10 customers by sales", new_thread: true },
    { id: "followup_us_b", question: "Only US customers", new_thread: false },
    { id: "followup_year_a", question: "Show sales by year", new_thread: true },
    { id: "followup_year_b", question: "Just 2004", new_thread: false },
    { id: "followup_top2_a", question: "Top 5 materials by quantity", new_thread: true },
    { id: "followup_top2_b", question: "Make it top 2", new_thread: false },
    { id: "ops_sat_failed", question: "Show failed SAT processing steps", new_thread: true },
    { id: "ops_sat_errors", question: "Latest SAT processing errors", new_thread: true },
    { id: "ops_edi_pipeline", question: "Show EDI invoice pipeline status", new_thread: true },
    { id: "edge_hello", question: "hello there", new_thread: true },
    { id: "edge_tables", question: "What tables do we have?", new_thread: true },
    { id: "edge_ambiguous_sales", question: "Show sales", new_thread: true },
    { id: "edge_gibberish", question: "asdfgh random text", new_thread: true },
    { id: "edge_sales_orders_rank", question: "Top customers by sales orders", new_thread: true },
  ];

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function startNew() {
    const btns = [...document.querySelectorAll("button")].filter((b) =>
      (b.textContent || "").includes("Start a new investigation")
    );
    const btn =
      btns.find((b) => (b.className || "").includes("emerald-600")) ||
      btns[btns.length - 1];
    if (btn) {
      btn.click();
      await sleep(900);
    }
  }

  async function ask(q, newThread) {
    const t0 = Date.now();
    const tablesBefore = document.querySelectorAll("table tbody").length;
    if (newThread) await startNew();

    const ta = document.querySelector("textarea");
    if (!ta) throw new Error("no textarea");

    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, q);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    ta.dispatchEvent(new Event("change", { bubbles: true }));
    await sleep(500);

    const send = document.querySelector('[aria-label="Send question"]');
    if (!send || send.disabled) throw new Error("send disabled");
    send.click();

    let sawCancel = false;
    const deadline = Date.now() + 300000;
    while (Date.now() < deadline) {
      const cancel = document.querySelector('[aria-label="Cancel analysis"]');
      if (cancel) {
        sawCancel = true;
        await sleep(2500);
        continue;
      }
      if (sawCancel) {
        await sleep(2000);
        break;
      }
      await sleep(1000);
    }

    const errEl = document.querySelector('[role="alert"] .text-red-700');
    const tables = document.querySelectorAll("table tbody");
    const lastTable = tables.length ? tables[tables.length - 1] : null;
    const rows = lastTable ? lastTable.rows.length : 0;
    const headings = [...document.querySelectorAll("h4")].map((h) => h.textContent || "");
    const questionShown = headings.some((h) => h.includes(q.slice(0, 24)));
    const blocks = [...document.querySelectorAll("p")].filter(
      (p) => p.textContent && p.textContent.includes(q.slice(0, 20))
    );
    const blockText = (blocks[blocks.length - 1]?.textContent || "").slice(0, 280);
    const isLimitation = /data limitation|cannot answer|not available|could not produce valid sql/i.test(
      document.body.innerText.slice(-2500)
    );
    const isClarify = /sales orders|billed invoices|clarify/i.test(document.body.innerText.slice(-1200));
    const isChat = /hello|how can i help|general/i.test(blockText) && q.toLowerCase().includes("hello");
    const ok =
      !errEl &&
      (isChat ||
        isClarify ||
        isLimitation ||
        (questionShown && rows > 0) ||
        (tables.length > tablesBefore && rows > 0));

    return {
      seconds: Math.round((Date.now() - t0) / 1000),
      rowCount: rows,
      error: errEl?.textContent || null,
      summary: blockText,
      isLimitation,
      isClarify,
      ok,
    };
  }

  window.__uiQaProgress = { status: "running", done: 0, total: tests.length, results: [] };

  (async () => {
    for (const t of tests) {
      try {
        const r = await ask(t.question, t.new_thread);
        window.__uiQaProgress.results.push({ ...t, ...r });
      } catch (e) {
        window.__uiQaProgress.results.push({
          ...t,
          ok: false,
          error: String(e.message || e),
          seconds: 0,
          rowCount: 0,
        });
      }
      window.__uiQaProgress.done += 1;
    }
    window.__uiQaProgress.status = "complete";
  })();

  return "started " + tests.length + " tests";
})();
