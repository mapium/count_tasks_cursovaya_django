(function () {
    "use strict";

    function getCsrfToken() {
        var input = document.querySelector("input[name='csrfmiddlewaretoken']");
        return input ? input.value : "";
    }

    function refreshCounters() {
        var board = document.getElementById("kanbanBoard");
        if (!board) return;
        board.querySelectorAll(".kanban-column").forEach(function (column) {
            var key = column.getAttribute("data-status");
            var counter = column.querySelector("[data-counter='" + key + "']");
            var tasksCount = column.querySelectorAll(".task-card").length;
            if (counter) counter.textContent = String(tasksCount);
        });
    }

    function updateStatusOnServer(taskId, targetColumn) {
        var url = window.DASHBOARD_STATUS_UPDATE_URL;
        if (!url) return Promise.resolve();

        var body = new URLSearchParams();
        body.set("task_id", String(taskId));
        body.set("target_column", String(targetColumn));

        return fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "X-CSRFToken": getCsrfToken()
            },
            body: body.toString()
        }).then(function (res) {
            if (!res.ok) {
                return res.json().then(function (data) {
                    throw new Error((data && data.error) || "Ошибка обновления статуса");
                }).catch(function () {
                    throw new Error("Ошибка обновления статуса");
                });
            }
            return res.json();
        });
    }

    function initDragAndDrop() {
        var board = document.getElementById("kanbanBoard");
        if (!board) return;

        var draggedCard = null;
        var sourceContainer = null;

        board.querySelectorAll(".task-card").forEach(function (task) {
            task.addEventListener("dragstart", function () {
                draggedCard = task;
                sourceContainer = task.parentElement;
                task.style.opacity = "0.6";
            });
            task.addEventListener("dragend", function () {
                task.style.opacity = "1";
            });
        });

        board.querySelectorAll(".kanban-column .kanban-tasks").forEach(function (container) {
            container.addEventListener("dragover", function (event) {
                event.preventDefault();
            });
            container.addEventListener("drop", function () {
                if (!draggedCard) return;

                var targetColumn = container.closest(".kanban-column");
                var nextStatus = targetColumn ? targetColumn.getAttribute("data-status") : null;
                var taskId = draggedCard.getAttribute("data-id");
                if (!nextStatus || !taskId) return;

                container.appendChild(draggedCard);
                refreshCounters();

                updateStatusOnServer(taskId, nextStatus)
                    .then(function () {
                        // Берем фактическое состояние из API после изменения статуса.
                        window.location.reload();
                    })
                    .catch(function (err) {
                        if (sourceContainer) sourceContainer.appendChild(draggedCard);
                        refreshCounters();
                        window.alert(err.message || "Не удалось обновить статус задачи.");
                    });
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initDragAndDrop();
        refreshCounters();
        var departmentFilter = document.getElementById("departmentFilter");
        var assigneeFilter = document.getElementById("assigneeFilter");
        var taskScopeFilter = document.getElementById("taskScopeFilter");
        var periodFilter = document.getElementById("periodFilter");

        function applyFilters() {
            var url = new URL(window.location.href);
            if (departmentFilter && !departmentFilter.disabled) {
                var depValue = (departmentFilter.value || "").trim();
                if (depValue) {
                    url.searchParams.set("department", depValue);
                } else {
                    url.searchParams.delete("department");
                }
            } else {
                url.searchParams.delete("department");
            }

            if (assigneeFilter) {
                var assigneeValue = (assigneeFilter.value || "").trim();
                if (assigneeValue) {
                    url.searchParams.set("assignee", assigneeValue);
                } else {
                    url.searchParams.delete("assignee");
                }
            }
            if (taskScopeFilter) {
                var taskScopeValue = (taskScopeFilter.value || "").trim();
                if (taskScopeValue) {
                    url.searchParams.set("task_scope", taskScopeValue);
                } else {
                    url.searchParams.delete("task_scope");
                }
            } else {
                url.searchParams.delete("task_scope");
            }
            if (periodFilter) {
                var periodValue = (periodFilter.value || "").trim();
                if (periodValue) {
                    url.searchParams.set("period", periodValue);
                } else {
                    url.searchParams.delete("period");
                }
            }
            window.location.assign(url.toString());
        }

        if (departmentFilter && !departmentFilter.disabled) {
            departmentFilter.addEventListener("change", applyFilters);
        }
        if (assigneeFilter) {
            assigneeFilter.addEventListener("change", applyFilters);
        }
        if (taskScopeFilter) {
            taskScopeFilter.addEventListener("change", applyFilters);
        }
        if (periodFilter) {
            periodFilter.addEventListener("change", applyFilters);
        }
    });
})();
