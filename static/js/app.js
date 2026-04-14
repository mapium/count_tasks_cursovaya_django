(function () {
    "use strict";

    const roleOrder = [
        "Администратор",
        "Руководитель предприятия",
        "Руководитель подразделения",
        "Работник"
    ];

    function initRoleSwitcher() {
        const badge = document.getElementById("roleBadge");
        const btn = document.getElementById("switchRoleBtn");
        if (!badge || !btn) {
            return;
        }

        let index = 0;
        btn.addEventListener("click", function () {
            index = (index + 1) % roleOrder.length;
            badge.textContent = roleOrder[index];
        });
    }

    function initEmployeeFuzzySearch() {
        const input = document.getElementById("employeeSearch");
        if (!input) {
            return;
        }
        if (document.querySelector(".employee-department-block")) {
            return;
        }

        const cards = Array.from(document.querySelectorAll(".employee-card:not(.employee-card--placeholder)"));
        input.addEventListener("input", function () {
            const query = input.value.trim().toLowerCase();
            cards.forEach(function (card) {
                const name = card.querySelector("h4")?.textContent?.toLowerCase() || "";
                const visible = !query || name.includes(query);
                card.style.display = visible ? "grid" : "none";
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initRoleSwitcher();
        initEmployeeFuzzySearch();
    });
})();
