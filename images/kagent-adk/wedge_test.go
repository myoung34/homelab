package eventqueue

import (
	"context"
	"testing"
	"time"

	"github.com/a2aproject/a2a-go/v2/a2a"
)

// Reproduces the 2026-10-14 homelab-agent wedge (a2aproject/a2a-go#395):
// one task's subscriber stops reading, then a late subscriber to that task
// parks under the manager's process-wide mutex. Queue creation for an
// unrelated task must not hang. Fails on stock v2.3.1; passes with #414.
func TestHomelabStalledSubscriberDoesNotBlockOtherTasks(t *testing.T) {
	ctx := context.Background()
	m := NewInMemoryManager()
	stalled := a2a.NewTaskID()
	w, err := m.CreateWriter(ctx, stalled)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := m.CreateReader(ctx, stalled); err != nil { // never read
		t.Fatal(err)
	}
	go func() {
		for i := 0; i < 100; i++ {
			_ = w.Write(ctx, &Message{Event: &a2a.Message{ID: "x"}})
		}
	}()
	time.Sleep(200 * time.Millisecond)
	go func() { _, _ = m.CreateReader(ctx, stalled) }() // late subscriber, e.g. UI reconnect
	time.Sleep(200 * time.Millisecond)

	done := make(chan error, 1)
	go func() { _, err := m.CreateWriter(ctx, a2a.NewTaskID()); done <- err }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("CreateWriter for an unrelated task blocked: process-wide deadlock")
	}
}
