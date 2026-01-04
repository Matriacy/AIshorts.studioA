const generateBtn = document.getElementById("generateBtn");
const promptInput = document.getElementById("promptInput");
const statusDiv = document.getElementById("status");
const resultDiv = document.getElementById("result");
const scriptText = document.getElementById("scriptText");
const videoLink = document.getElementById("videoLink");

generateBtn.addEventListener("click", async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) return alert("Enter a prompt");

  statusDiv.textContent = "⏳ Generating...";
  resultDiv.classList.add("hidden");

  try {
    const response = await fetch("/generate-video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt })
    });

    const data = await response.json();

    scriptText.textContent = data.script;
    videoLink.href = data.video_url;
    resultDiv.classList.remove("hidden");
    statusDiv.textContent = "✅ Done";
  } catch (err) {
    statusDiv.textContent = "❌ Error";
    console.error(err);
  }
});
