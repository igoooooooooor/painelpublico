const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../frontend/scripts/app.script.js'), 'utf8');

function setup(hash, ready = true) {
  const events = {}, calls = [], targets = new Map();
  const context = {
    state: { view: 'profile' }, location: { hash },
    document: { getElementById: id => targets.get(id) },
    window: { scrollY: 120, scrollTo: (...args) => calls.push(['position', ...args]), addEventListener: (name, fn) => { events[name] = fn; } },
    render() {}, applyLocation() {},
  };
  for (const id of ['profile-cost', 'profile-work', 'profile-alerts']) {
    if (ready) targets.set(id, { scrollIntoView: options => calls.push([id, options.block]) });
  }
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('let pendingProfileAnchor'), source.indexOf("\ndocument.addEventListener('click', e =>", source.indexOf('let pendingProfileAnchor'))) + '\nthis.refresh = rerender;', context);
  vm.runInContext(source.slice(source.lastIndexOf("if (typeof window !== 'undefined'")), context);
  return { context, events, calls, targets };
}

test('all profile summary hashes scroll to their section instead of resetting to the top', () => {
  for (const id of ['profile-cost', 'profile-work', 'profile-alerts']) {
    const { events, calls } = setup('#' + id);
    events.popstate();
    assert.deepEqual(calls, [[id, 'start']]);
  }
});

test('direct profile anchor waits for the API render and does not hijack later scrolls', () => {
  const { context, calls, targets } = setup('#profile-alerts', false);
  assert.equal(context.scrollToProfileAnchor(true), false);
  context.refresh();
  targets.set('profile-alerts', { scrollIntoView: () => calls.push(['alerts']) });
  context.refresh();
  context.refresh();
  assert.deepEqual(calls, [['position', 0, 120], ['alerts'], ['position', 0, 120]]);
  assert.match(source, /syncLocation\('replace'\);\nscrollToProfileAnchor\(true\);/);
});

test('back to an unanchored page clears pending profile scrolling', () => {
  const { context, events, calls, targets } = setup('#profile-work', false);
  context.scrollToProfileAnchor(true);
  context.location.hash = '';
  events.popstate();
  targets.set('profile-work', { scrollIntoView: () => calls.push(['unexpected']) });
  context.refresh();
  assert.deepEqual(calls, [['position', 0, 0], ['position', 0, 120]]);
});
