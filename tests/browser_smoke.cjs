// Run: NODE_PATH=<Playwright packages> node tests/browser_smoke.cjs
// Uses an isolated stdlib backend and Edge, with no cloud API or production data.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const path = require('node:path');

async function run() {
  const root = path.resolve(__dirname, '..');
  const fixture = spawn(process.env.LINGXI_TEST_PYTHON || 'python', ['-u', 'tests/browser_fixture.py'], { cwd: root, stdio: ['pipe', 'pipe', 'inherit'] });
  let browser;
  try {
    const base = await new Promise((resolve, reject) => {
      const lines = createInterface({ input: fixture.stdout });
      const timer = setTimeout(() => reject(new Error('UI server did not start')), 10000);
      lines.on('line', line => {
        try { const result = JSON.parse(line); if (result.base) { clearTimeout(timer); resolve(result.base); } } catch {}
      });
      fixture.once('error', reject);
      fixture.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited: ${code}`)); });
    });
    browser = await chromium.launch({ channel: process.env.LINGXI_TEST_BROWSER || 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['microphone'] });
    const errors = [], failures = [];
    context.on('page', page => {
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => {
        if (response.status() >= 400 && response.status() !== 401) failures.push(`${response.status()} ${response.url()}`);
      });
    });
    const learning = await context.newPage();
    const consolePage = await context.newPage();
    await learning.goto(base + '/companion#study');
    await learning.waitForFunction(() => window.LingXiCompanion?.getReady());
    const id = await learning.evaluate(() => LingxiIdentity.get());
    await consolePage.goto(base + '/console');
    assert.equal(await consolePage.evaluate(() => LingxiIdentity.get()), id);

    // Two tabs must update without navigation/reload or the 10/15s poll timer.
    const title = '跨页即时同步验收';
    await learning.locator('[data-open-task]:visible,[data-action="new-task"]:visible').first().click();
    await learning.locator('#taskTitle').fill(title);
    await learning.locator('#saveTask').click();
    await learning.locator('#taskDialog').waitFor({ state: 'hidden' });
    await consolePage.locator('#taskList').getByText(title, { exact: true }).waitFor({ timeout: 5000 });
    await consolePage.locator('#taskList article').filter({ hasText: title }).getByRole('button', { name: '标记完成', exact: true }).click();
    await learning.waitForFunction(title => ![...document.querySelectorAll('#studyTaskList strong')].some(el => el.textContent === title), title, { timeout: 5000 });

    // Device protection must not break the original console's microphone/TTS.
    // Actual UI handlers send to the local backend, whose loopback bypass is off.
    const audioResponses = [];
    consolePage.on('response', response => {
      if (/\/api\/audio\/(transcribe|speech)$/.test(response.url())) audioResponses.push(response);
    });
    await consolePage.locator('#audioToggle').check();
    await consolePage.locator('#talkButton').dispatchEvent('pointerdown');
    await consolePage.waitForFunction(() => app.audioCapture?.chunks.length > 0 && performance.now() - app.audioCapture.startedAt > 500);
    await consolePage.locator('#talkButton').dispatchEvent('pointerup');
    await consolePage.waitForResponse(response => response.url().endsWith('/api/audio/speech'), { timeout: 15000 });
    assert.equal(audioResponses.length, 2);
    for (const response of audioResponses) {
      assert.equal(response.status(), 200, response.url());
      assert.equal(response.request().postDataJSON().device_id, id);
    }

    // Pairing uses only the submitted code; unsaved input cannot poison polls.
    await learning.goto(base + '/companion?pair=1#settings');
    await learning.waitForFunction(() => window.LingXiCompanion?.getReady());
    const pair = async (device, code) => {
      await learning.locator('#deviceId').fill(device);
      await learning.locator('#deviceToken').fill(code);
      await learning.locator('#switchDevice').click();
      await learning.waitForFunction(() => !document.querySelector('#switchDevice').disabled);
    };
    await pair('physical-ui-a', 'ui-test-only-token');
    assert.equal(await learning.evaluate(() => LingxiIdentity.get()), 'physical-ui-a');
    await learning.locator('#deviceToken').fill('unsaved-wrong-token');
    const pollingStatus = await learning.evaluate(async () => (await LingXiCompanion.getJSON('/api/companion/settings?device_id=physical-ui-a')).device_id);
    assert.equal(pollingStatus, 'physical-ui-a');
    await learning.evaluate(() => { const item = document.createElement('div'); item.textContent = '旧设备的对话'; document.querySelector('#messages').append(item); });
    await pair('physical-ui-b', '');
    assert.equal(await learning.evaluate(() => LingxiIdentity.get()), 'physical-ui-a', 'blank code must not reuse old credentials');
    assert.equal(await learning.locator('#messages').getByText('旧设备的对话').count(), 1);
    await pair('physical-ui-b', 'ui-test-only-token');
    assert.equal(await learning.evaluate(() => LingxiIdentity.get()), 'physical-ui-b');
    assert.equal(await learning.locator('#messages').getByText('旧设备的对话').count(), 0);
    assert.equal(await consolePage.evaluate(() => LingxiIdentity.get()), id, 'pairing is scoped to one tab');
    await learning.goto(base + '/console');
    assert.equal(await learning.evaluate(() => LingxiIdentity.get()), 'physical-ui-b');
    await learning.locator('.identity-reset').click();
    assert.equal(await learning.evaluate(() => LingxiIdentity.get()), id);

    // Chat works without the removed artwork; reload still revalidates assets.
    await learning.goto(base + '/companion#home');
    await learning.waitForFunction(() => window.LingXiCompanion?.getReady());
    assert.equal(await learning.locator('#petImage, #petBadge, .motion-details').count(), 0);
    // All visible action icons resolve to actual SVG shapes, including after
    // toggling focus mode; decorative icons must not replace accessible names.
    const icons = await learning.locator('#view-home svg use, .rail-nav svg use').evaluateAll(nodes => nodes.filter(n => n.closest('svg').getBoundingClientRect().width > 0).map(n => ({ href: n.getAttribute('href'), width: n.getBBox().width })));
    assert.ok(icons.length >= 15);
    assert.ok(icons.every(icon => icon.href?.startsWith('#i-') && icon.width > 0));
    await learning.locator('#showcaseToggle').click();
    assert.equal(await learning.locator('#showcaseToggle use').getAttribute('href'), '#i-collapse');
    await learning.keyboard.press('Escape');
    assert.equal(await learning.locator('#showcaseToggle use').getAttribute('href'), '#i-expand');
    await learning.locator('#voiceReply').uncheck();
    await learning.locator('#messageInput').fill('你好');
    await learning.locator('#sendButton').click();
    await learning.locator('#messages .message.assistant').filter({ hasText: '你好，我在这里。' }).waitFor();
    const cdp = await context.newCDPSession(learning);
    await cdp.send('Network.enable');
    const cached = [];
    cdp.on('Network.responseReceivedExtraInfo', event => { if (event.statusCode === 304) cached.push(event.requestId); });
    await learning.reload();
    await learning.waitForFunction(() => window.LingXiCompanion?.getReady());
    assert.ok(cached.length > 0, 'reload should revalidate existing resources');
    await learning.setViewportSize({ width: 390, height: 844 });
    assert.ok(await learning.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));

    assert.ok(await learning.locator('#messageInput').evaluate(el => el.getBoundingClientRect().bottom < innerHeight - 65), 'mobile composer visible above navigation');

    // The compact bottom navigation must retain a way to leave a paired device.
    await learning.goto(base + '/companion?pair=1#settings');
    await learning.waitForFunction(() => window.LingXiCompanion?.getReady());
    await pair('physical-ui-a', 'ui-test-only-token');
    await learning.locator('.mobile-menu > summary').click();
    await learning.locator('.mobile-menu [data-reset-identity]').click();
    await learning.waitForFunction(() => window.LingXiCompanion?.getReady());
    assert.equal(await learning.evaluate(() => LingxiIdentity.get()), id, 'mobile users can leave their paired device');

    // Event delivery falls back to storage events without BroadcastChannel.
    const fallback = await browser.newContext();
    await fallback.addInitScript(() => { window.BroadcastChannel = undefined; });
    const first = await fallback.newPage(), second = await fallback.newPage();
    await first.goto(base + '/demo'); await second.goto(base + '/demo');
    await second.evaluate(() => window.addEventListener('lingxi:data-changed', () => { window.changed = true; }));
    await first.evaluate(() => LingxiIdentity.notify(LingxiIdentity.get()));
    await second.waitForFunction(() => window.changed === true, null, { timeout: 3000 });
    assert.notEqual(await first.evaluate(() => LingxiIdentity.get()), id);
    assert.deepEqual(errors, []);
    assert.deepEqual(failures, []);
    console.log(JSON.stringify({ crossTabTaskSync: true, consoleMicrophoneAndTts: true, pairingDraftIsolated: true, pairingFailurePreservesState: true, deviceSwitchClearsMessages: true, browserCache304: cached.length, mobileLayout: true, storageFallback: true, errors, failures }));
  } finally {
    if (browser) await browser.close();
    fixture.stdin.end();
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
