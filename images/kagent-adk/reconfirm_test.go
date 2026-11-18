package llminternal_test

// homelab: repro for google/adk-go#2233. A tool that asks for confirmation
// again when resumed (kagent's remote A2A tool does this whenever a
// subagent pauses a second time) must produce a second
// adk_request_confirmation, or the client never sees the question.

import (
	"encoding/json"
	"testing"

	"google.golang.org/genai"

	"google.golang.org/adk/v2/agent"
	"google.golang.org/adk/v2/agent/llmagent"
	"google.golang.org/adk/v2/internal/llminternal"
	"google.golang.org/adk/v2/model"
	"google.golang.org/adk/v2/session"
	"google.golang.org/adk/v2/tool"
	"google.golang.org/adk/v2/tool/toolconfirmation"
)

type askAgainTool struct{}

func (askAgainTool) Name() string        { return mockToolName }
func (askAgainTool) Description() string { return "asks again on resume" }
func (askAgainTool) IsLongRunning() bool { return false }
func (askAgainTool) Declaration() *genai.FunctionDeclaration {
	return &genai.FunctionDeclaration{Name: mockToolName}
}

// Run asks again, naming the confirmation it was resumed with, so a test
// can tell which request a resume was matched to.
func (askAgainTool) Run(ctx agent.Context, _ any) (map[string]any, error) {
	if err := ctx.RequestConfirmation("after "+ctx.ToolConfirmation().Hint, nil); err != nil {
		return nil, err
	}
	return map[string]any{"status": "pending"}, nil
}

func confirmationRequest(id, hint string) *session.Event {
	return &session.Event{
		Author: "testAgent",
		LLMResponse: model.LLMResponse{Content: &genai.Content{Parts: []*genai.Part{{
			FunctionCall: &genai.FunctionCall{
				Name: toolconfirmation.FunctionCallName,
				ID:   id,
				Args: map[string]any{
					"originalFunctionCall": map[string]any{"name": mockToolName, "args": map[string]any{}, "id": mockFunctionCallID},
					"toolConfirmation":     toolconfirmation.ToolConfirmation{Hint: hint},
				},
			},
		}}}},
	}
}

// approval answers request id. Like kagent, the answer carries a payload
// back to the tool; here it is the round marker hint.
func approval(t *testing.T, id, hint string) *session.Event {
	t.Helper()
	approved, err := json.Marshal(toolconfirmation.ToolConfirmation{Confirmed: true, Hint: hint})
	if err != nil {
		t.Fatal(err)
	}
	return &session.Event{
		Author: "user",
		LLMResponse: model.LLMResponse{Content: &genai.Content{Parts: []*genai.Part{{
			FunctionResponse: &genai.FunctionResponse{
				Name:     toolconfirmation.FunctionCallName,
				ID:       id,
				Response: map[string]any{"response": string(approved)},
			},
		}}}},
	}
}

// followUpHints runs the resume processor over events and returns the hint
// of every confirmation request it emits.
func followUpHints(t *testing.T, events []*session.Event) []string {
	t.Helper()
	tools := []tool.Tool{askAgainTool{}}
	agnt, err := llmagent.New(llmagent.Config{Name: "testAgent", Model: &testModel{}, Tools: tools})
	if err != nil {
		t.Fatal(err)
	}
	ctx := createInvocationContext(t, agnt, &fakeSession{events: events})
	var hints []string
	for ev, err := range llminternal.RequestConfirmationRequestProcessor(ctx, &model.LLMRequest{}, &llminternal.Flow{Tools: tools}) {
		if err != nil {
			t.Fatal(err)
		}
		for _, p := range ev.LLMResponse.Content.Parts {
			if p.FunctionCall == nil || p.FunctionCall.Name != toolconfirmation.FunctionCallName {
				continue
			}
			orig, _ := p.FunctionCall.Args["originalFunctionCall"].(*genai.FunctionCall)
			if orig == nil || orig.ID != mockFunctionCallID {
				t.Errorf("confirmation for %v, want original call %q", p.FunctionCall.Args["originalFunctionCall"], mockFunctionCallID)
			}
			tc, _ := p.FunctionCall.Args["toolConfirmation"].(toolconfirmation.ToolConfirmation)
			hints = append(hints, tc.Hint)
		}
	}
	return hints
}

func TestResumedToolCanRequestConfirmationAgain(t *testing.T) {
	got := followUpHints(t, []*session.Event{
		confirmationRequest("confirm-1", "first"),
		approval(t, "confirm-1", "first"),
	})
	if len(got) != 1 || got[0] != "after first" {
		t.Fatalf("follow-up hints = %q, want [\"after first\"]", got)
	}
}

// The second answer resumes against the second request, not the first.
func TestSecondApprovalResumesSecondRequest(t *testing.T) {
	pending := &session.Event{
		Author: "testAgent",
		LLMResponse: model.LLMResponse{Content: &genai.Content{Parts: []*genai.Part{{
			FunctionResponse: &genai.FunctionResponse{Name: mockToolName, ID: mockFunctionCallID, Response: map[string]any{"status": "pending"}},
		}}}},
	}
	got := followUpHints(t, []*session.Event{
		confirmationRequest("confirm-1", "first"),
		approval(t, "confirm-1", "first"),
		pending,
		confirmationRequest("confirm-2", "after first"),
		approval(t, "confirm-2", "after first"),
	})
	if len(got) != 1 || got[0] != "after after first" {
		t.Fatalf("follow-up hints = %q, want [\"after after first\"]", got)
	}
}
