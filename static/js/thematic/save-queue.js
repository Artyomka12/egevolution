'use strict';
// No browser state or grading: independently testable sequential autosave queue.
class ThematicSaveQueue {
  constructor(send, key) { this.send = send; this.key = key; this.items = new Map(); this.tail = Promise.resolve(); }
  seed(id, value, revision) { this.items.set(id, {value: structuredClone(value), revision, generation: 0, saved: 0, pending: null, conflict: false}); }
  edit(id, value) { const s = this.items.get(id); s.value = structuredClone(value); s.generation++; }
  dirty(id) { const s = this.items.get(id); return !!s.pending || s.generation !== s.saved; }
  enqueue(work) { const run = this.tail.then(work); this.tail = run.catch(() => {}); return run; }
  async save(id) {
    const s = this.items.get(id);
    if (s.conflict) throw Object.assign(new Error('Ответ изменён в другой вкладке. Сверьте его перед продолжением.'), {status: 409, item_id: id});
    while (this.dirty(id)) {
      if (!s.pending) s.pending = {body: {answer: structuredClone(s.value), expected_revision: s.revision, mutation_id: this.key()}, generation: s.generation};
      const pending = s.pending;
      let result;
      try { result = await this.send(id, pending.body); }
      catch (e) { if (e.status === 409) s.conflict = true; throw e; }
      s.revision = result.revision; s.saved = pending.generation; s.pending = null;
      if (result.current_revision !== undefined && result.current_revision !== result.revision) {
        s.conflict = true;
        throw Object.assign(new Error('После сохранения ответ изменён в другой вкладке.'), {status: 409, item_id: id});
      }
    }
  }
  flush() { return this.enqueue(async () => { for (const id of this.items.keys()) await this.save(id); }); }
}
if (typeof module !== 'undefined') module.exports = ThematicSaveQueue;
else window.ThematicSaveQueue = ThematicSaveQueue;
