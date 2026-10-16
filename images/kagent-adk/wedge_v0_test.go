package eventqueue

import (
	"context"
	"testing"
	"time"

	"github.com/a2aproject/a2a-go/a2a"
)

// Reproduces the 2026-10-15 homelab-agent wedge on a2a-go v0.3.15, the module
// kagent 0.10.3's A2A server actually runs: a chat stream stops reading, the
// broker blocks forever handing it an event, and a late subscriber (a UI
// reconnect) blocks in Get. taskexec.localManager.Resubscribe holds the
// manager's process-wide mutex across that Get, so no task can start or
// resubscribe anywhere in the pod. Fails on stock v0.3.15; passes with
// a2a-go-v0-stalled-subscriber.patch.
func TestHomelabStalledSubscriberIsDroppedV0(t *testing.T) {
	ctx := context.Background()
	m := NewInMemoryManager(WithQueueBufferSize(1), WithSubscriberTimeout(100*time.Millisecond))
	task := a2a.NewTaskID()
	writer, err := m.GetOrCreate(ctx, task)
	if err != nil {
		t.Fatal(err)
	}
	stalled, err := m.GetOrCreate(ctx, task) // never read
	if err != nil {
		t.Fatal(err)
	}

	writes := make(chan error, 1)
	go func() {
		for i := 0; i < 3; i++ {
			if err := writer.Write(ctx, &a2a.Message{ID: "x"}); err != nil {
				writes <- err
				return
			}
		}
		writes <- nil
	}()
	select {
	case err := <-writes:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("writer blocked on a subscriber that stopped reading")
	}

	got := make(chan bool, 1)
	go func() { _, ok := m.Get(ctx, task); got <- ok }() // late subscriber, e.g. UI reconnect
	select {
	case ok := <-got:
		if !ok {
			t.Fatal("late subscriber could not attach to a live task")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("late subscriber blocked behind the stalled one")
	}

	// The dropped subscriber drains what it had buffered, then sees the close.
	for {
		if _, _, err := stalled.Read(ctx); err != nil {
			if err != ErrQueueClosed {
				t.Fatalf("stalled reader: got %v, want ErrQueueClosed", err)
			}
			break
		}
	}
}

func TestHomelabDefaultSubscriberTimeoutV0(t *testing.T) {
	m := NewInMemoryManager().(*inMemoryManager)
	if m.subscriberTimeout != 5*time.Minute {
		t.Fatalf("default subscriber timeout = %v, want 5m", m.subscriberTimeout)
	}
}
