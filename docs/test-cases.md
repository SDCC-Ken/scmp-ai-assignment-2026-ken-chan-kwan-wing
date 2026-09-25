# Test cases: create, update and delete (cancel) of Leave and Claim

All cases run offline with a scripted AI and a recording fake of the submission adapter, against an
in-memory SQLite database. Run them with `cd backend && uv run pytest -q tests/chat`. The rules
behind each case are in [business-rules.md](business-rules.md). "Delete" means cancelling a request
(requests are never physically deleted, so the audit trail stays complete).

## Create leave

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| CL-S1 | Full-day annual leave, confirmed | Saved, submitted, `pending_approval`, audit rows, approver notified | `test_full_day_leave_confirm_saves_everything` |
| CL-S2 | Half-day (morning), single day | 0.5 working day | `test_half_day_morning` |
| CL-S3 | Multi-day, afternoon start and morning end | Half days counted at both ends | `test_multi_day_pm_start_am_end` |
| CL-S4 | Range across a weekend and the 1 Oct National Day holiday | Working days skip both | `test_range_over_weekend_and_national_day` |
| CL-S5 | Sick leave back-dated 3 days / on any past date | Accepted | `test_sick_leave_back_dated_three_days`, `test_sick_leave_may_start_on_any_past_date` |
| CL-S6 | Leave starting today, any type | Accepted | `test_leave_starting_today_is_accepted_for_every_type` |
| CL-S7 | Single date, user answers "just one day" | One-day card | `test_single_date_then_just_one_day_gives_a_one_day_card` |
| CL-S8 | Single date, user gives an end date | Range card | `test_single_date_then_an_explicit_end_date_gives_a_range` |
| CL-F1 | End date before start date | Asks for the end date again | `test_end_before_start_asks_for_the_end_date` |
| CL-F2 | Annual leave starting in the past | Rejected; says sick leave can be back-dated | `test_past_start_is_rejected_except_for_sick_leave` |
| CL-F3 | Weekend-only range / holiday-only range | Rejected with the reason | `test_weekend_only_range_is_rejected`, `test_holiday_only_range_names_the_holiday` |
| CL-F4 | Invalid half-day combination | Asks full, morning or afternoon | `test_invalid_half_day_combination` |
| CL-F5 | Missing fields | Asked one at a time | `test_missing_fields_are_asked_one_at_a_time` |
| CL-F6 | Unknown leave type | Lists the supported types | `test_unknown_leave_type_lists_the_supported_types` |
| CL-F7 | Single date, unclear answer | Question is asked again | `test_single_date_then_nonsense_asks_again` |
| CL-F8 | AI reports ambiguity or low confidence | No card; asks to clarify | `test_ambiguity_from_the_llm_asks_and_shows_no_card`, `test_low_confidence_asks_for_clarification_without_changes` |
| CL-F9 | Request "for" another person's email | Refused | `test_someone_elses_email_is_refused` |
| CL-W1 | Year with no holiday data | Calculated (weekends only) with a card warning | `test_year_without_holiday_data_adds_a_warning` |

## Create claim

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| CC-S1 | Valid claim, confirmed | Saved, submitted, `pending_approval` | `test_valid_claim_confirm_saves_everything` |
| CC-S2 | Amount with 2 decimals | Accepted exactly | `test_two_decimal_amount` |
| CC-S3 | Amount 50,000.00 and old receipts | Accepted (no cap yet) | `test_amount_of_exactly_50000_is_accepted_until_phase_3`, `test_receipt_today_and_old_receipts_are_accepted` |
| CC-F1 | Zero or negative amount | Rejected, asks again | `test_zero_or_negative_amount` |
| CC-F2 | More than 2 decimals | Rejected, never rounded | `test_more_than_two_decimals_is_rejected_not_rounded` |
| CC-F3 | Non-HKD currency | Rejected, asks for HKD | `test_non_hkd_currency_is_rejected` |
| CC-F4 | Receipt date in the future | Rejected, asks the date | `test_future_receipt_date_is_rejected` |
| CC-F5 | Missing fields / unknown claim type | Asked, lists types | `test_missing_fields_are_asked_one_at_a_time`, `test_unknown_claim_type_lists_the_supported_types` |
| CC-F6 | Amount too large or not a number | Refused | `test_amount_is_limited_to_12_digits_in_total`, `test_nonfinite_amount_from_the_model_is_not_stored` |

## Update (change) an existing request

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| UP-S1 | Change the end date of a pending leave | Diff card, then re-submitted and updated | `test_change_end_date_of_a_pending_leave` |
| UP-S2 | Change a half-day part | Working days recalculated | `test_change_the_half_day_part` |
| UP-S3 | Change the amount of a pending claim | Updated | `test_change_the_amount_of_a_pending_claim` |
| UP-S4 | Edit a failed submission, then retry | Becomes `pending_approval` | `test_edit_a_failed_submission_then_retry_succeeds`, `test_edit_a_failed_submission_that_now_succeeds` |
| UP-S5 | Only one editable request | Target inferred; also by date hint | `test_target_is_inferred_when_only_one_request_can_be_edited`, `test_target_resolved_by_a_date_hint` |
| UP-F1 | Approved, rejected or cancelled request | Explained; not editable | `test_approved_request_cannot_be_edited`, `test_rejected_request_cannot_be_edited`, `test_cancelled_request_cannot_be_edited` |
| UP-F2 | Another employee's request / unknown id | "Not found" | `test_another_employees_request_looks_nonexistent`, `test_nonexistent_request_id` |
| UP-F3 | Edit that makes the request invalid | Explained, can be fixed | `test_invalid_edit_is_explained_and_can_be_fixed` |
| UP-F4 | ReqRes fails during the change | Original data kept | `test_adapter_failure_during_amendment_leaves_the_original_intact` |
| UP-F5 | No change given / same value / ambiguous target | Asks what to change, or lists candidates | `test_update_with_no_change_specified_asks_what_to_change`, `test_same_value_is_not_a_change`, `test_ambiguous_target_lists_the_candidates` |
| UP-F6 | Request became final before the user confirmed | Not applied | `test_edit_that_becomes_final_meanwhile_is_not_applied` |
| UP-F7 | Moving a started annual leave's start into the past | Rejected | `test_moving_the_start_date_into_the_past_is_rejected` |
| UP-S6 | Extending an already-started annual leave (start unchanged) | Allowed | `test_extending_an_already_started_leave_is_allowed` |

## Delete (cancel)

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| CX-S1 | Cancel a pending leave / claim | Card, confirm, `cancelled` | `test_cancel_a_pending_leave`, `test_cancel_a_pending_claim` |
| CX-S2 | Cancel a failed submission | Cancelled with no call to ReqRes | `test_cancel_a_submission_failed_request_makes_no_external_call` |
| CX-S3 | Discard the card | Nothing changes | `test_discard_leaves_everything_unchanged` |
| CX-F1 | Approved or rejected request | Cannot be cancelled | `test_approved_request_cannot_be_cancelled`, `test_rejected_request_cannot_be_cancelled` |
| CX-F2 | Already cancelled | Explained | `test_already_cancelled_request` |
| CX-F3 | Another employee's request / unknown id | "Not found" | `test_another_employees_request_cannot_be_cancelled`, `test_nonexistent_request_id` |
| CX-F4 | Request became final before confirming | Not applied | `test_cancel_confirmation_after_the_request_became_final` |

## Confirmation and submission

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| CF-1 | Confirm with no open card / old card / other conversation | 409 | `test_confirm_without_an_open_card_is_409`, `test_superseded_card_is_409_and_the_new_card_still_works`, `test_card_from_another_conversation_is_409` |
| CF-2 | Double or concurrent confirm | One request, one ReqRes call | `test_double_confirm_creates_exactly_one_request_and_one_external_call`, `test_concurrent_confirms_have_exactly_one_winner` |
| CF-3 | ReqRes fails, then retry | `submission_failed`, then `pending_approval` | `test_adapter_failure_saves_submission_failed_then_retry_succeeds`, `test_retry_that_fails_again_offers_another_retry` |
| CF-4 | Only defined fields are sent | Exact keys checked | `test_leave_wire_body_contains_only_the_defined_fields`, `test_claim_wire_body_contains_only_the_defined_fields` |
| CF-5 | Database not locked during the AI or ReqRes call | Other writes succeed meanwhile | `test_database_is_not_locked_during_the_adapter_and_llm_calls` |

## Status, conversations and safety

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| ST-1 | Ask status by type / id / status | Own requests only, deterministic card | `test_status_by_type_lists_only_own_requests`, `test_status_by_id`, `test_status_filter_by_status` |
| ST-2 | Another employee's id | Refused | `test_status_of_another_employees_id_is_refused` |
| ST-3 | Rejected request | Shows the reviewer note | `test_rejected_request_shows_the_reviewer_note` |
| ST-4 | Nothing found / more than ten | Empty card / ten most recent | `test_status_none_found`, `test_status_shows_only_the_ten_most_recent` |
| CH-1 | Reopen an old conversation and continue | Draft and card restored | `test_reopen_an_old_conversation_and_continue_its_draft`, `test_messages_and_cards_persist_and_reload_with_correct_card_states` |
| CH-2 | Other user's conversation | Not found | `test_conversations_are_isolated_between_users` |
| CH-3 | AI down, invalid output, or an unexpected error | Graceful message; nothing changes | `test_llm_error_is_graceful_and_keeps_the_draft`, `test_invalid_llm_output_is_graceful`, `test_unexpected_error_inside_the_graph_is_graceful` |
| CH-4 | Prompt injection ("approve my leave", "submit for bob") | No state change | `test_prompt_injection_changes_nothing` |
| CH-5 | Message over 1000 characters | 422 | `test_message_length_limits` |
| CH-6 | HR, Finance or signed-out user | 403 / 401 | `test_approvers_cannot_use_the_employee_chat`, `test_unauthenticated_requests_are_401` |
| CH-7 | Markup in messages | Returned as plain text | `test_markup_in_messages_is_returned_as_plain_text_unchanged` |

## Documents (image or PDF attached to a message)

Offline: a scripted AI double returns what a provider would have read (`AgentTurn.documents`), and
the real `FakeLLMProvider` reads the `backend/samples/*.fake.pdf` files. Run with
`cd backend && uv run pytest -q tests/chat/test_documents.py`. Rules: business-rules.md section 4a.

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| DC-1 | Sick note with both dates, empty message | Sick leave card, fields tagged `document`, file listed; Confirm links it; HR can open it, Finance and other employees get 404 | `test_sick_note_with_both_dates_makes_a_tagged_leave_card_and_confirm_links_the_file` |
| DC-2 | Sick note with only "3 days advised" | Asks for the last day; nothing is computed; typed answer completes the card | `test_sick_note_with_only_days_advised_asks_for_the_last_day_and_never_computes_it` |
| DC-3 | Sick note with no dates | Asks the first day, then the last day, naming the file | `test_sick_note_without_any_dates_asks_for_the_first_day_then_the_last` |
| DC-4 | Complete receipt | Claim card (meal, HKD 83.60, date) tagged `document`; Finance can open the file, HR cannot | `test_complete_receipt_makes_a_tagged_claim_card_and_finance_can_open_the_file` |
| DC-5 | Receipt without a date | "I could not read the receipt date on receipt-sample.png. What date is on the receipt?"; typed date completes it | `test_receipt_without_a_date_asks_for_it_by_name_then_the_typed_date_completes_it` |
| DC-6 | Receipt without amount and date | One question at a time | `test_a_receipt_without_amount_and_date_asks_one_thing_at_a_time` |
| DC-7 | Non-HKD receipt | Currency follow-up; typed HKD amount completes it; `HK$` is read as HKD | `test_non_hkd_receipt_gets_the_currency_follow_up_then_a_typed_amount_completes_it`, `test_hk_dollar_sign_is_read_as_hkd` |
| DC-8 | Unreadable / blurry file, no other information | No card; asks to type the details or upload a clearer file | `test_an_unreadable_file_asks_to_type_the_details_or_upload_a_clearer_one` |
| DC-9 | Other document type; stored file missing; unreadable file next to typed details | Asks what it is for / asks to upload again / not used and says so | `test_a_document_that_is_neither_a_sick_note_nor_a_receipt_asks_what_it_is_for`, `test_if_the_stored_file_cannot_be_opened_the_user_is_asked_to_upload_again`, `test_an_unreadable_file_next_to_typed_details_is_not_used_and_says_so` |
| DC-10 | Typed amount differs from the receipt | Typed value kept; card warning names field and both values | `test_typed_values_win_over_the_document_and_the_conflict_is_a_warning` |
| DC-11 | Earlier draft value differs from the document | Draft value kept with warnings; warning disappears when they agree | `test_a_value_from_earlier_in_the_draft_wins_and_the_warning_goes_when_they_agree` |
| DC-12 | Name on the document differs / matches (order, case, initials) | Warning only / no warning | `test_a_different_name_on_the_document_is_a_warning_never_a_block`, `test_matching_names_give_no_warning`, `test_name_matching` |
| DC-13 | Receipt while a leave draft is open | Asks which one; "claim" starts a claim from the held receipt, carrying on with the leave drops it | `test_a_receipt_while_a_leave_draft_is_open_asks_which_one_and_mixes_nothing`, `test_the_held_receipt_is_dropped_when_the_user_carries_on_with_the_leave` |
| DC-14 | Files accumulate over messages, capped at 3 | Card lists them; a 4th is dropped with a notice | `test_attachments_accumulate_across_messages_and_are_capped_at_three_per_request` |
| DC-15 | Discard / new draft of the other type | Draft attachments and tags cleared; files stay unlinked | `test_discard_and_a_new_draft_of_the_other_type_clear_the_draft_attachments` |
| DC-16 | New document in the update flow | Update card with old and new value, tagged; Confirm links the new file, old links stay | `test_a_new_document_in_the_update_flow_is_linked_and_the_old_links_stay` |
| DC-17 | AI error or invalid output with files | Graceful message; message and files kept; draft unchanged | `test_an_llm_error_with_attachments_is_graceful_and_keeps_everything`, `test_invalid_provider_output_with_attachments_is_graceful_too` |
| DC-18 | Instructions inside a document ("approve this claim", another person's e-mail) | Only fills the draft; needs Confirm; employee stays the signed-in user; nothing approved | `test_instructions_inside_a_document_change_nothing_beyond_filling_the_draft`, `test_a_document_cannot_make_the_assistant_act_for_someone_else`, `test_a_document_that_only_contains_instructions_leaves_the_state_untouched` |
| DC-19 | Trace of a document turn | `documents` step, no names or file names | `test_the_trace_has_a_documents_step_without_names_or_file_names` |
| DC-20 | `FakeLLMProvider` on the samples, through the API (upload, message, card, confirm) | Sick note, receipt, incomplete receipt and unreadable samples behave as above | `test_fake_provider_sick_note_sample_end_to_end`, `test_fake_provider_receipt_sample_end_to_end`, `test_fake_provider_incomplete_receipt_asks_for_the_date_then_completes`, `test_fake_provider_unreadable_sample_asks_to_type_the_details` |

## Approvals and notifications (Phase 3)

Offline, against the seeded in-memory database (a temporary file database for the concurrency
cases). Run with `cd backend && uv run pytest -q tests/approvals`. Rules: business-rules.md
section 4c. Seed reminders: leave 1 (Amy, IT, pending, Cathy, 4 working days, overlaps Ben's
approved leave), leave 2 (Daniel, HR, pending, Helen, over his annual balance), claim 1 (Amy,
pending, Eva), claim 2 (Daniel, pending, Eva, takes HR over its limit).

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| AP-1 | Amy, Ben or Daniel opens the queue, a detail or posts a decision; a signed-out user does the same | 403 for employees, 401 signed out | `test_employees_have_no_queue`, `test_unauthenticated_is_401` |
| AP-2 | Cathy, Helen and Eva list their queues | Cathy: leave 1; Helen: leave 2; Eva: claim 2 then claim 1 (oldest first); none sees another queue | `test_each_approver_sees_only_their_own_queue`, `test_claims_are_ordered_oldest_submitted_first`, `test_queues_cover_the_configured_requesters` |
| AP-3 | Requests that are decided, cancelled, draft, failed, assigned to someone else or self-assigned | Never listed; a decided request leaves the list | `test_only_pending_requests_appear`, `test_a_request_assigned_to_someone_else_is_not_listed`, `test_own_request_is_never_in_the_queue`, `test_helen_queue_can_be_empty_and_decided_items_disappear` |
| AP-4 | List flags on the showcase items | Overlap 1 on leave 1; over_limit on leave 2 and claim 2; sick over 10 days flagged, personal never; attachment flag | `test_list_item_shape_and_flags_for_the_seed_showcase`, `test_over_limit_flag_for_sick_and_personal_leave`, `test_has_attachments_flag` |
| AP-5 | Detail of leave 1 | Fields, balance 15 / 1.5 / 4 / 9.5 left, overlap with Ben, no warning, no e-mail | `test_leave_detail_matches_the_seed_numbers` |
| AP-6 | Detail of an over-balance leave and an over-budget claim | Warning "Over the annual leave balance by 1 day. You decide." / "This claim takes HR over its annual claim limit by HKD 1,941.05. You decide." | `test_over_balance_leave_warns_but_is_still_shown`, `test_over_budget_claim_detail` |
| AP-7 | Personal / unpaid leave, sick over its balance, half-day parts, attachments, team overlap details | No balance and no warning / sick warning / card wording / URLs that open / pending colleague counted, other department not | `test_personal_and_unpaid_leave_have_no_balance`, `test_sick_leave_over_the_balance_warns_with_the_type`, `test_half_day_parts_are_shown_like_the_chat_card`, `test_attachments_are_listed_with_download_urls`, `test_team_overlap_counts_pending_colleagues_but_not_other_departments` |
| AP-8 | Detail for an unknown id, another approver's request, the other type, an unknown type, a decided or cancelled request, own request | Identical 404 | `test_not_found_cases_share_one_body`, `test_not_pending_is_404_for_detail`, `test_own_request_is_not_inspectable` |
| AP-9 | Approve or reject, with and without a note; note with spaces, empty, 500 and 501 characters | Status, reviewer, time and note stored; note trimmed / null / 422 over 500 | `test_approve_leave_with_a_note`, `test_reject_claim_with_a_note`, `test_the_note_is_optional_for_both_decisions`, `test_note_is_trimmed_and_empty_becomes_null`, `test_a_note_of_501_characters_is_refused`, `test_trailing_spaces_do_not_count_towards_the_limit` |
| AP-10 | Bad decision value, missing fields, wrong note type, no CSRF header | 422 / 403, nothing changes | `test_an_invalid_decision_is_422`, `test_missing_body_fields_and_bad_note_types_are_422`, `test_a_post_without_the_csrf_header_is_refused` |
| AP-11 | Second decision, cancelled meanwhile, wrong role, self-assigned request, unknown or foreign request | 409 keeping the first outcome / 409 / 403 / 404 / 404 | `test_a_second_decision_is_409_and_keeps_the_first`, `test_a_cancelled_request_can_no_longer_be_decided`, `test_wrong_role_is_403`, `test_self_approval_is_impossible`, `test_not_found_cases_share_one_body` |
| AP-12 | Over-balance leave and over-budget claim are approved | Allowed (limits never block) | `test_over_the_limit_requests_can_still_be_approved` |
| AP-13 | Audit row of an approval, a rejection and an over-limit approval | One row with actor, from/to status, snapshot numbers, overlap count, employee id; no note text | `test_approving_a_leave_writes_one_audit_row_with_the_numbers`, `test_rejecting_an_over_budget_claim_audits_the_budget_snapshot`, `test_the_note_text_is_never_in_the_audit_metadata` |
| AP-14 | Notifications created by a decision | Requester gets approved / rejected; the approver's own "new request" notifications become read; nothing on a refusal | `test_the_requester_is_notified_of_the_decision`, `test_the_approvers_own_new_request_notifications_are_marked_read`, `test_notifications_are_not_created_when_the_decision_is_refused` |
| AP-15 | Two decisions at the same moment; a decision losing after its status check; a failure while writing | Exactly one winner (200 and 409), one audit row, one notification; nothing written by the loser or the failed write | `test_concurrent_decisions_have_exactly_one_winner`, `test_a_decision_that_loses_after_its_status_check_is_a_conflict`, `test_a_failure_while_writing_rolls_everything_back` |
| AP-16 | Notification list: seed rows, order, limit 1 to 50, unread count | Correct titles, bodies and links; newest first; 422 outside 1..50 | `test_seed_notifications_compose_correctly`, `test_newest_first_default_limit_and_bounds`, `test_equal_timestamps_are_ordered_by_id_descending` |
| AP-17 | Mark read, mark all read, someone else's id, signed out, no CSRF header | 204 idempotent / only own rows / 404 / 401 / 403 | `test_mark_one_read_is_idempotent`, `test_read_all_only_touches_the_callers_rows`, `test_someone_elses_or_unknown_id_is_404`, `test_unauthenticated_and_csrf` |
| AP-18 | Composition of every event type, links, legacy types | See rule A-19 and A-20 | `test_titles_and_bodies_for_every_event_type`, `test_link_only_for_the_assigned_approver_while_pending`, `test_unknown_and_legacy_event_types_get_a_neutral_title` |
| AP-19 | Balances and department budget after approve and after reject | Approved days / amount move only on approve | `test_approving_leave_deducts_the_days_and_rejecting_does_not`, `test_my_balances_endpoint_reflects_the_decision`, `test_approving_a_claim_uses_up_the_department_budget`, `test_rejecting_a_claim_leaves_the_department_budget_unchanged` |
| AP-20 | Chat after a decision: status card note, edit and cancel refused | Note shown; "can't be cancelled / changed any more" | `test_the_status_card_shows_the_reviewer_note_of_a_rejected_request`, `test_the_employee_can_no_longer_cancel_a_decided_request`, `test_the_employee_can_no_longer_edit_a_decided_request` |
| AP-21 | Who opens an attachment while pending, approved, rejected and cancelled | See rule A-24 | `test_the_approver_can_open_the_files_while_pending_and_after_the_decision`, `test_files_of_a_rejected_request_stay_downloadable_for_the_approver`, `test_files_of_a_cancelled_request_are_not_available_to_the_approver` |

## Balance, approver awareness and stated dates (Phase 3-C)

Offline: scripted AI double, the seed and the real `FakeLLMProvider`; the Ollama provider runs
against a mock HTTP transport that misbehaves like the live model (fills today's date). Run with
`cd backend && uv run pytest -q tests/chat/test_balance_and_approver.py
tests/chat/test_unstated_dates.py tests/llm/test_llm_dates_currency.py`. Rules: business-rules.md
L-13, L-14, C-06, C-11 and section 4d. Seed reminders (2026): Amy annual 15 entitled, 1.5 used,
4 pending; Ben annual 18 / 2 used, sick 10 / 1 used; Daniel annual 15 / 10 used (5 left).

| ID | Scenario | Expected outcome | Test |
| --- | --- | --- | --- |
| BA-1 | Amy: annual leave 2 to 4 Nov | Card info "Annual leave 2026": "15 days entitled, 1.5 used, 13.5 left; 10.5 left after this request (pending requests are not counted)"; her 4 pending days are not deducted | `test_annual_leave_card_shows_the_balance_before_and_after`, `test_only_approved_leave_is_deducted_pending_is_not` |
| BA-2 | Sick leave (Ben), personal and unpaid leave, a claim | Sick line "10 days entitled, 1 used, 9 left; 8 left ..."; no line for personal, unpaid or claims | `test_sick_leave_card_has_a_sick_balance_line`, `test_personal_and_unpaid_leave_have_no_balance_line`, `test_claim_cards_get_no_balance_line` |
| BA-3 | Daniel asks for 6.5 working days with 5 left | Extra warning line "This is 1.5 days over your annual leave balance. Your approver will see this and decide."; Submit still works and creates the request | `test_going_over_the_balance_adds_a_warning_line_but_never_blocks` |
| BA-4 | Exactly the remaining days (5 of 5); 1 day over | "0 left after this request" without warning; "1 day over" (singular) | `test_exactly_using_the_remaining_days_is_not_over_the_balance`, `test_one_day_over_says_1_day_not_1_days` |
| BA-5 | Leave starting in 2027; 30 Dec 2026 to 5 Jan 2027 | 2027 line (15 days, none used); the start year (2026) is used for the split range | `test_the_balance_year_follows_the_start_date` |
| BA-6 | No annual entitlement row | "No leave balance is set up for this leave type"; sick line still shown | `test_a_missing_entitlement_is_said_not_invented` |
| BA-7 | Update card of a pending leave | Info line with the balance after the change (11.5 left after); changing the type to personal removes it | `test_the_update_card_shows_the_balance_after_the_change`, `test_changing_the_type_on_an_update_moves_the_balance_line` |
| BA-8 | "How many annual leave days do I have left?" | `balance_card` (year 2026, annual and sick lines with numbers) and a deterministic sentence; only the caller's numbers | `test_check_balance_answers_with_a_balance_card_and_deterministic_text`, `test_check_balance_uses_only_the_signed_in_users_numbers`, `test_check_balance_with_a_message_about_someone_else_still_shows_only_your_own` |
| BA-9 | Balance question without entitlements; one entitlement only | "No leave balance is set up for you yet." and no card; only that type listed | `test_check_balance_without_any_entitlement_says_so_and_has_no_card`, `test_check_balance_with_only_one_entitlement_lists_only_that_type` |
| BA-10 | Balance question with a draft and card open; a model that quotes numbers | Draft and card untouched (the card still confirms); model numbers never shown | `test_check_balance_does_not_disturb_an_open_draft_or_card`, `test_check_balance_never_needs_the_model_to_say_a_number` |
| BA-11 | Fake provider phrases ("leave balance", "how much sick leave do I have", "remaining leave", ...) | `check_balance`; requests and status questions are not stolen | `test_check_balance_phrases`, `test_balance_intent_does_not_steal_other_requests`, `test_check_balance_with_the_fake_provider_end_to_end` |
| BA-12 | New leave or claim for a user without that approver (Amy with the approver removed) | "I can't file a leave request for you yet: no approver is configured for you (this is outside the PoC scope). Please contact HR." / "... a claim ... Please contact Finance."; no draft, no card, nothing sent; the other request type still works | `test_no_leave_approver_refuses_up_front_with_no_draft_and_no_card`, `test_no_claim_approver_refuses_claims_and_names_finance` |
| BA-13 | Refusal while another draft is open; details for an existing draft; inactive approver; approver removed between card and Confirm; Helen and Eva | Other draft and card kept; not blocked; reason given without an e-mail; Confirm-time guard still refuses; 403 at the API | `test_the_refusal_keeps_the_users_other_open_draft`, `test_details_for_an_existing_draft_are_not_blocked_by_the_up_front_check`, `test_an_inactive_approver_is_refused_up_front_with_the_reason`, `test_the_confirm_time_check_is_still_the_second_guard`, `test_users_without_any_approver_still_get_no_chat_at_all` |
| BA-14 | Result after Submit and after a Retry | "... is now waiting for approval by Cathy Ng." (Helen for Daniel and Cathy, Eva for claims), names only | `test_the_leave_result_names_the_assigned_approver`, `test_the_claim_result_names_eva`, `test_a_retry_after_a_failed_submission_names_the_approver_too`, `test_the_approver_follows_a_changed_configuration` |
| BA-15 | Status card | Each request has `approver_name` (never an e-mail); null when unassigned | `test_status_card_items_carry_the_approver_name`, `test_status_card_approver_name_is_null_when_unassigned` |
| BA-16 | "Claim HKD 180 for a taxi" (model returns today's date) | "What is the date on the receipt?", no card, nothing stored; then "yesterday" completes the card | `test_a_taxi_claim_without_a_date_asks_for_the_receipt_date`, `test_the_answer_to_the_date_question_then_completes_the_card`, `test_ollama_taxi_without_a_date_does_not_keep_todays_date` |
| BA-17 | Receipt dates that ARE stated: yesterday, today, "22 Sep", ISO, "last Friday", 22/9, Chinese | Accepted | `test_a_stated_receipt_date_is_accepted`, `test_ollama_keeps_a_stated_receipt_date`, `test_date_expressions_are_recognised` |
| BA-18 | Dates from a document; typed guess next to a receipt; receipt with no date | Document date accepted; the document's date replaces a guessed one; still asked by name | `test_a_date_read_from_a_receipt_is_accepted_without_any_typed_date`, `test_a_typed_guess_next_to_a_receipt_is_replaced_by_the_documents_date`, `test_a_receipt_without_a_date_still_asks_for_it_by_name` |
| BA-19 | Leave with no dates stated; a model that invents an end date; "only that day please" | Start date asked, invented dates ignored; the repeated draft start is accepted as end | `test_leave_dates_the_user_never_gave_are_asked_not_assumed`, `test_an_invented_end_date_after_a_stated_start_is_asked_not_kept`, `test_the_one_day_reply_needs_no_new_date_words`, `test_ollama_one_day_reply_keeps_the_drafts_own_start_date` |
| BA-20 | `$`, `HK$`, `HKD$`, "dollars", "HK dollars" | HKD all the way to the ReqRes payload (`amount` as typed) | `test_dollar_wordings_are_hkd_all_the_way_to_the_request`, `test_currency_wording`, `test_currency_guard_for_text_turns`, `test_ollama_lunch_with_a_dollar_sign_is_hkd` |
| BA-21 | `USD`, `US$`, "US dollars", `EUR` | Existing follow-up "Claims are accepted in HKD only, and you mentioned USD..."; an HKD amount then completes the claim | `test_us_dollars_are_still_rejected_with_the_existing_follow_up`, `test_another_explicit_currency_is_rejected_by_its_code`, `test_after_a_rejected_currency_an_hkd_amount_completes_the_claim` |
| BA-22 | Real `FakeLLMProvider` end to end | Taxi without a date asks; "80 HK dollars" is HKD; "50 US dollars" is rejected | `test_the_fake_provider_end_to_end_taxi_without_a_date_and_dollar_words` |
| BA-23 | `check_balance` in both providers | Gemini prompt, Ollama compact prompt, wire schema and flat schema list it; it is not an approval action | `test_the_gemini_wire_schema_mirrors_the_new_intent`, `test_the_ollama_flat_schema_lists_the_new_intent`, `test_both_prompts_explain_check_balance_and_no_default_dates`, `test_a_check_balance_reply_round_trips_through_both_parsers` |
