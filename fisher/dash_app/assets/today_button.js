/* 「当日」快捷按钮注入（方案 B：日期弹窗头部、翻页箭头「▶」旁）。
 *
 * 适配 Dash 4.x 自研日期组件（dash-datepicker-*，radix 弹层），
 * 不再是旧版 react-dates（.DateRangePicker_picker 已不存在）。
 *
 * 结构：#<组件id> ... > .dash-datepicker-content（弹窗）
 *                     > .dash-datepicker-controls（◀ 月份标题 ▶ 头部行）
 * 注入：在 controls 行末尾（Next month 箭头之后）追加 .fq-today-btn。
 * 点击：代理触发页面上隐藏的 Dash 回调按钮（dc-range-today-btn / export-today-btn），
 *       并派发 Escape 关闭弹层（radix 监听 document keydown Escape）。 */
(function () {
    var MAP = [
        { root: "date-range-picker", btn: "dc-range-today-btn" },
        { root: "export-start-date", btn: "export-today-btn" },
        { root: "export-end-date", btn: "export-today-btn" },
    ];

    function findControls(rootEl) {
        /* 非 portal 模式弹窗渲染在组件内部；portal 模式兜底扫全局唯一打开的弹窗 */
        var content = rootEl.querySelector(".dash-datepicker-content");
        if (!content) {
            var all = document.querySelectorAll(".dash-datepicker-content.dash-datepicker-portal");
            if (all.length === 1) content = all[0];
        }
        return content ? content.querySelector(".dash-datepicker-controls") : null;
    }

    function inject(controlsEl, btnId) {
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
            var hidden = document.getElementById(btnId);
            if (hidden) hidden.click();
            /* 稍后关闭弹层：radix 监听 document 的 Escape */
            setTimeout(function () {
                document.dispatchEvent(new KeyboardEvent("keydown", {
                    key: "Escape", code: "Escape", keyCode: 27, bubbles: true,
                }));
            }, 150);
        });
        controlsEl.appendChild(b);
    }

    var scheduled = false;
    var obs = new MutationObserver(function () {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(function () {
            scheduled = false;
            for (var i = 0; i < MAP.length; i++) {
                var m = MAP[i];
                var rootEl = document.getElementById(m.root);
                if (!rootEl) continue;
                var controls = findControls(rootEl);
                if (controls) inject(controls, m.btn);
            }
        });
    });
    obs.observe(document.body, { childList: true, subtree: true });
})();
