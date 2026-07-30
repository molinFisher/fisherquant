/* 「当日」快捷按钮注入（适配 Dash 4.x 自研日期组件 dash-datepicker）。
 *
 * dcc.DatePickerRange / dcc.DatePickerSingle 在 Dash 4.x 底层为 dash-datepicker，
 * 弹窗 class 为 .dash-datepicker-content，头部控制行 class 为 .dash-datepicker-controls。
 * 本脚本在弹窗打开时，在其 .dash-datepicker-controls 行右侧注入「当日」按钮。
 *
 * 两种配置：
 *   - { root, btn }：单按钮，点击即触发（数据中心日期范围 / 导出单日期）。
 *   - { root, startBtn, endBtn }：范围选择器，根据当前聚焦的是开始还是结束输入，
 *     分别触发 startBtn 或 endBtn（行情看板日线）。
 *
 * 范围选择器需在 DatePickerRange 上设置 start_date_id / end_date_id，
 * JS 通过 focusin/mousedown 判断当前激活侧。
 */
(function () {
    var MAP = [
        { root: "date-range-picker", wrapper: "date-range-picker-wrapper", btn: "dc-range-today-btn" },
        { root: "export-start-date", wrapper: "export-start-date-wrapper", btn: "export-today-btn" },
        { root: "export-end-date", wrapper: "export-end-date-wrapper", btn: "export-today-btn" },
        { root: "qb-daily-date-range", wrapper: "qb-daily-date-range-wrapper", startBtn: "qb-daily-today-start-btn", endBtn: "qb-daily-today-end-btn" },
    ];

    var ACTIVE = { rootId: null, side: null };

    function log() {
        if (window._fqTodayDebug) console.log.apply(console, ["[today-btn]"].concat(Array.prototype.slice.call(arguments)));
    }

    function closeDatepicker() {
        /* dash-datepicker 关闭按钮或 Escape 均可关闭弹层 */
        setTimeout(function () {
            var closeBtn = document.querySelector(".dash-datepicker-close-button");
            if (closeBtn) {
                closeBtn.click();
                return;
            }
            document.dispatchEvent(new KeyboardEvent("keydown", {
                key: "Escape", code: "Escape", keyCode: 27, bubbles: true,
            }));
        }, 50);
    }

    function clickHidden(btnId) {
        var hidden = document.getElementById(btnId);
        if (hidden) {
            hidden.click();
            log("clicked hidden", btnId);
        } else {
            log("hidden button not found", btnId);
        }
    }

    function injectButton(controlsEl) {
        if (controlsEl.querySelector(".fq-today-btn")) return;
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = "当日";
        b.className = "fq-today-btn";
        b.title = "设为今天";
        b.addEventListener("mousedown", function (e) {
            e.preventDefault();
            e.stopPropagation();
        });
        b.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            var cfg = null;
            for (var i = 0; i < MAP.length; i++) {
                if (MAP[i].root === ACTIVE.rootId) {
                    cfg = MAP[i];
                    break;
                }
            }
            if (!cfg) cfg = findCfgByActiveElement();
            if (!cfg) {
                log("no active config");
                return;
            }

            if (cfg.btn) {
                clickHidden(cfg.btn);
            } else if (cfg.startBtn && cfg.endBtn) {
                clickHidden(ACTIVE.side === "end" ? cfg.endBtn : cfg.startBtn);
            }
            closeDatepicker();
        });
        /* 放在 controls 行末尾（Next month 箭头之后） */
        controlsEl.appendChild(b);
        log("injected");
    }

    function getWrapper(cfg) {
        return document.getElementById(cfg.wrapper || cfg.root);
    }

    function findCfgByActiveElement() {
        var active = document.activeElement;
        if (!active) return null;
        for (var i = 0; i < MAP.length; i++) {
            var m = MAP[i];
            var wrapper = getWrapper(m);
            if (!wrapper) continue;
            if (wrapper === active || wrapper.contains(active)) {
                ACTIVE.rootId = m.root;
                ACTIVE.side = detectSide(active, wrapper, m);
                return m;
            }
        }
        return null;
    }

    function detectSide(target, wrapper, cfg) {
        if (!cfg.startBtn || !cfg.endBtn) return null;
        var rootId = cfg.root;
        var tid = target.id || "";
        /* 自定义 id */
        if (tid === rootId + "-start-input") return "start";
        if (tid === rootId + "-end-input") return "end";
        /* Dash 默认 id */
        if (tid === rootId) return "start";
        if (tid === rootId + "-end-date") return "end";
        if (target.tagName === "INPUT") {
            /* input 的 name 属性 */
            var name = target.getAttribute("name");
            if (name === "startDate") return "start";
            if (name === "endDate") return "end";
            /* 兜底：按 input 在 wrapper 内的顺序 */
            var inputs = wrapper.querySelectorAll("input");
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i] === target) return i === 0 ? "start" : "end";
            }
        }
        return "start";
    }

    function scanAndInject() {
        var contents = document.querySelectorAll(".dash-datepicker-content");
        contents.forEach(function (content) {
            /* 只处理真正弹出的、可见的弹窗 */
            var rect = content.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;
            var controls = content.querySelector(".dash-datepicker-controls");
            if (controls) injectButton(controls);
        });
    }

    function initTracking() {
        MAP.forEach(function (cfg) {
            var wrapper = getWrapper(cfg);
            if (!wrapper || wrapper._fqTracked) return;
            wrapper._fqTracked = true;
            wrapper.addEventListener("focusin", function (e) {
                ACTIVE.rootId = cfg.root;
                ACTIVE.side = detectSide(e.target, wrapper, cfg);
                log("focusin", cfg.root, ACTIVE.side, e.target);
            });
            wrapper.addEventListener("mousedown", function (e) {
                /* mousedown 比 click 更早触发，弹窗常在 mousedown 时打开 */
                ACTIVE.rootId = cfg.root;
                ACTIVE.side = detectSide(e.target, wrapper, cfg) || ACTIVE.side || "start";
                log("mousedown", cfg.root, ACTIVE.side, e.target);
            });
        });
    }

    var scheduled = false;
    var obs = new MutationObserver(function () {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(function () {
            scheduled = false;
            scanAndInject();
        });
    });

    function boot() {
        initTracking();
        obs.observe(document.body, { childList: true, subtree: true });
        scanAndInject();
        log("booted");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
