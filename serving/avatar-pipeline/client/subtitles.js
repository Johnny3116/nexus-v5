// subtitles.js

export function showSubtitleStreaming(text, totalDurationSeconds, mode = "word") {
  const container = document.getElementById('subtitle-container');
  container.innerHTML = ''; // Clear existing content
  container.classList.add('visible');

  let segments = mode === "letter" ? [...text] : text.split(' ');
  let totalSteps = segments.length;
  let delay = (totalDurationSeconds * 1000 *0.7) / totalSteps;

  segments.forEach((segment, i) => {
    const span = document.createElement('span');
    span.style.opacity = '0';
    span.style.transition = 'opacity 0.3s ease';
    span.textContent = mode === "word" ? segment + ' ' : segment;

    container.appendChild(span);

    setTimeout(() => {
      span.style.opacity = '1';
    }, i * delay);
  });

  // Hide after total duration
  setTimeout(() => {
    container.classList.remove('visible');
  }, totalDurationSeconds * 1000 + 900);
}
