import { test, expect } from '@playwright/test';

// Minimal valid 1x1 PNG
const TEST_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==',
  'base64'
);

test('이미지 업로드 에러 재현 및 진단', async ({ page }) => {
  // 콘솔 로그 수집
  const consoleLogs: string[] = [];
  page.on('console', (msg) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

  // 네트워크 요청 수집
  const allRequests: string[] = [];
  page.on('request', (req) => allRequests.push(`${req.method()} ${req.url()}`));

  // 네트워크 에러 수집
  page.on('requestfailed', (req) => {
    console.log(`=== REQUEST FAILED === ${req.method()} ${req.url()} | ${req.failure()?.errorText}`);
  });

  // 1. 분석 페이지 이동
  console.log('=== Step 1: 분석 페이지 이동 ===');
  await page.goto('/ohs/analysis');
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: 'test-results/01-page-loaded.png', fullPage: true });
  console.log('페이지 로드 완료');

  // 2. 이미지 업로드
  console.log('=== Step 2: 이미지 업로드 ===');
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({
    name: 'test-workplace.png',
    mimeType: 'image/png',
    buffer: TEST_PNG,
  });

  // 미리보기 확인
  await expect(page.locator('img[alt="미리보기"]')).toBeVisible({ timeout: 5000 });
  await page.screenshot({ path: 'test-results/02-image-preview.png', fullPage: true });
  console.log('이미지 미리보기 표시됨');

  // 3. 분석 버튼 클릭 + API 응답 캡처
  console.log('=== Step 3: 분석 실행 ===');
  const analyzeButton = page.getByRole('button', { name: '위험요소 분석하기' });
  await expect(analyzeButton).toBeVisible();

  // API 응답 인터셉트
  const responsePromise = page.waitForResponse(
    (resp) => resp.url().includes('analysis'),
    { timeout: 30_000 }
  ).catch(() => null);

  await analyzeButton.click();
  await page.screenshot({ path: 'test-results/03-after-click.png', fullPage: true });

  // 4. 응답 또는 에러 대기
  console.log('=== Step 4: 응답 대기 ===');
  const response = await responsePromise;

  if (response) {
    console.log(`=== API RESPONSE ===`);
    console.log(`URL: ${response.url()}`);
    console.log(`Status: ${response.status()} ${response.statusText()}`);
    try {
      const body = await response.text();
      console.log(`Body: ${body.substring(0, 2000)}`);
    } catch {}
  } else {
    console.log('=== API 응답 없음 (30초 타임아웃) ===');
  }

  // 에러 메시지 또는 성공 네비게이션 대기
  const outcome = await Promise.race([
    page.locator('[class*="red"]').first().waitFor({ timeout: 35_000 })
      .then(() => 'error' as const),
    page.waitForURL('**/result/**', { timeout: 35_000 })
      .then(() => 'success' as const),
  ]).catch(() => 'timeout' as const);

  console.log(`=== OUTCOME: ${outcome} ===`);

  if (outcome === 'error') {
    const errorEl = page.locator('[class*="red"]').first();
    const errorText = await errorEl.textContent().catch(() => 'N/A');
    console.log(`ERROR TEXT: ${errorText}`);
  }

  await page.screenshot({ path: 'test-results/04-final-state.png', fullPage: true });

  // 5. 진단 로그 출력
  console.log('\n=== ALL REQUESTS ===');
  allRequests.forEach((r) => console.log(r));

  console.log('\n=== CONSOLE LOGS ===');
  consoleLogs.forEach((l) => console.log(l));
});
