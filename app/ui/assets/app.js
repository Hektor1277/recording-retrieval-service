const form = document.querySelector("#request-form");
const requestPreview = document.querySelector("#request-preview");
const statusPreview = document.querySelector("#job-status");
const resultsPreview = document.querySelector("#job-results");

export function buildRequestPayload(formData) {
  const timestamp = Date.now();
  return {
    requestId: `standalone-${timestamp}`,
    source: {
      kind: "owner-entity-check",
      ownerRunId: `standalone-run-${timestamp}`,
      requestedBy: "owner-tool",
    },
    items: [
      {
        itemId: `standalone-item-${timestamp}`,
        recordingId: `standalone-item-${timestamp}`,
        workId: "standalone-work",
        composerId: "standalone-composer",
        workTypeHint: "orchestral",
        sourceLine: formData.get("sourceLine") || "",
        seed: {
          title: formData.get("title") || "",
          composerName: formData.get("composerName") || "",
          composerNameLatin: formData.get("composerNameLatin") || "",
          workTitle: formData.get("workTitle") || "",
          workTitleLatin: formData.get("workTitleLatin") || "",
          catalogue: formData.get("catalogue") || "",
          performanceDateText: formData.get("performanceDateText") || "",
          venueText: "",
          albumTitle: "",
          label: "",
          releaseDate: "",
          credits: [],
          links: [],
          notes: "",
        },
        requestedFields: [
          "links",
          "performanceDateText",
          "venueText",
          "albumTitle",
          "label",
          "releaseDate",
          "notes",
          "images",
        ],
      },
    ],
    options: {
      maxConcurrency: 1,
      timeoutMs: 3000,
      returnPartialResults: true,
    },
  };
}

function renderJson(node, value) {
  node.textContent = JSON.stringify(value, null, 2);
}

async function waitForResults(jobId) {
  for (let index = 0; index < 40; index += 1) {
    const status = await fetch(`/v1/jobs/${encodeURIComponent(jobId)}`).then((response) => response.json());
    renderJson(statusPreview, status);
    if (!["queued", "running"].includes(status.status)) {
      return fetch(`/v1/jobs/${encodeURIComponent(jobId)}/results`).then((response) => response.json());
    }
    await new Promise((resolve) => window.setTimeout(resolve, 150));
  }
  throw new Error("Timed out waiting for job results");
}

form?.addEventListener("input", () => {
  renderJson(requestPreview, buildRequestPayload(new FormData(form)));
});

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = buildRequestPayload(new FormData(form));
  renderJson(requestPreview, payload);
  renderJson(statusPreview, { state: "submitting" });
  renderJson(resultsPreview, { state: "pending" });

  const accepted = await fetch("/v1/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  }).then((response) => response.json());

  const results = await waitForResults(accepted.jobId);
  renderJson(resultsPreview, results);
});

if (form) {
  renderJson(requestPreview, buildRequestPayload(new FormData(form)));
}
