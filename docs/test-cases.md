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
