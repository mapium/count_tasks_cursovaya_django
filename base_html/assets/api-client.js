(function () {
    "use strict";

    const DEFAULT_API_BASE = "http://localhost:8000/api";
    function getApiBase() {
        return window.KANBAN_API_BASE || DEFAULT_API_BASE;
    }

    async function request(path, options) {
        const url = `${getApiBase()}${path}`;
        const response = await fetch(url, {
            headers: { "Content-Type": "application/json" },
            ...options
        });
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        if (response.status === 204) return null;
        return response.json();
    }

    window.ApiClient = {
        employees: {
            list: () => request("/employees/"),
            create: (payload) => request("/employees/", { method: "POST", body: JSON.stringify(payload) }),
            update: (id, payload) => request(`/employees/${id}/`, { method: "PUT", body: JSON.stringify(payload) }),
            delete: (id) => request(`/employees/${id}/`, { method: "DELETE" })
        },
        tasks: {
            list: () => request("/tasks/"),
            create: (payload) => request("/tasks/", { method: "POST", body: JSON.stringify(payload) }),
            updateStatus: (id, payload) => request(`/tasks/${id}/status/`, { method: "PATCH", body: JSON.stringify(payload) })
        },
        reports: {
            departmentTasks: (params) => request(`/reports/department-tasks/?${new URLSearchParams(params).toString()}`),
            staffDistribution: () => request("/reports/staff-distribution/")
        }
    };
})();
