# -*- coding: utf-8 -*-
"""
Views for the participant registration and payment for the event.
"""
# from annoying.functions import get_object_or_None
# from django.contrib.auth import login, authenticate
# from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.shortcuts import get_object_or_404
from django.http import HttpResponseRedirect
# from django.template import loader, Context
from django.core.urlresolvers import reverse
from django.views.generic.edit import CreateView
# from django.views.generic.detail import DetailView
from django.views.generic.base import TemplateView

# from django.contrib.sites.models import get_current_site
from django.contrib import messages
from django.conf import settings
# from django.contrib import messages

from pymill import pymill

from .models import Ticket, TicketType
from applications.conventions.models import Convention
from .forms import TicketForm

import logging
logger = logging.getLogger('debug')


class DateCheckMixin(object):

    """ Checks that signup is not closed. """

    closed_url = 'signup-closed'

    def date_overdue(self, request, *args, **kwargs):
        return HttpResponseRedirect(reverse(self.closed_url))

    def dispatch(self, request, *args, **kwargs):
        if timezone.now() > self.overdue:
            return self.date_overdue(request, *args, **kwargs)
        return super(DateCheckMixin, self).dispatch(request, *args, **kwargs)


class ClosedView(TemplateView):

    """ Main view when ticket sales is closed. """
    template_name = 'festival-over.html'
    convention = Convention.objects.latest('end_time')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(convention=self.convention)
        return context


class TicketStartView(TemplateView):
    template_name = 'ticket-start.html'
    convention = Convention.objects.next()

    def get_context_data(self, **kwargs):
        """Adds sold_out to context"""
        context = super().get_context_data(**kwargs)
        ticket_types = TicketType.objects.filter(status=TicketType.FOR_SALE, ticket_pool__convention=self.convention)
        context.update(ticket_types=ticket_types)
        context.update(convention=self.convention)
        return context

    def dispatch(self, request, *args, **kwargs):
        if self.convention is None:
            return ClosedView.as_view()(request, *args, **kwargs)
        else:
            return super().dispatch(request, *args, **kwargs)


class TicketCreateView(CreateView):
    model = Ticket
    form_class = TicketForm
    template_name = 'ticket-create.html'
    next_url_label = 'hashid-schedule'

    def dispatch(self, request, *args, **kwargs):
        slug = self.kwargs.get('ticket_type_slug')
        self.ticket_type = get_object_or_404(
            TicketType.objects.exclude(status=TicketType.COMING_SOON).exclude(status=TicketType.SOLD_OUT),
            slug=slug,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Adds sold_out to context"""
        context = super().get_context_data(**kwargs)
        context.update(
            ticket_type=self.ticket_type,
            convention=self.ticket_type.ticket_pool.convention,
            paymill_live=settings.PAYMILL_LIVE,
        )
        return context

    def get_next_url(self):
        return reverse(
            'hashid-schedule',
            args=[self.object.hashid]
        )

    def form_valid(self, form):
        self.object = form.save(ticket_type=self.ticket_type)
        return HttpResponseRedirect(self.get_next_url())


class TicketDetailView(TemplateView):

    model = Ticket
    context_object_name = 'ticket'
    slug_field = 'hashid'
    slug_url_kwarg = 'hashid'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            ticket_type=self.ticket.ticket_type,
            ticket=self.ticket,
            convention=self.ticket.convention,
            paymill_live=settings.PAYMILL_LIVE,
        )
        return context

    def dispatch(self, request, *args, **kwargs):
        self.ticket = get_object_or_404(
            Ticket,
            hashid=self.kwargs.get('hashid')
        )
        return super().dispatch(request, *args, **kwargs)


class TicketPayView(TicketDetailView):

    """ Show payment form """

    template_name = 'ticket-pay.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            PAYMILL_PUBLIC_KEY=settings.PAYMILL_PUBLIC_KEY,
            PAYMILL_TEST_MODE='true' if settings.DEBUG else 'false',
        )
        return context

    def render_to_response(self, context):
        if self.ticket.status != Ticket.ORDERED:
            return HttpResponseRedirect(self.ticket.get_absolute_url())

        return super().render_to_response(context)

    def post(self, *args, **kwargs):
        """ Process payment from PayMill """
        PAYMILL_SUCCESS_CODE = 20000
        paymill_token = self.request.POST.get('paymill_token')
        private_key = settings.PAYMILL_PRIVATE_KEY

        paymill = pymill.Pymill(private_key)

        credit_card = paymill.new_card(token=paymill_token,)
        description = '{ticket} for {person}'.format(
            ticket=self.ticket.ticket_type,
            person=self.ticket.get_full_name(),
        )

        transaction = paymill.transact(
            amount=self.ticket.ticket_type.price * 100,
            currency=self.ticket.ticket_type.currency,
            payment=credit_card,
            description=description,
        )

        response_status = paymill.response_code2text(transaction.response_code)

        logger.debug(
            '{time} {name} {response}'.format(
                time=timezone.now(),
                name=self.ticket.get_full_name(),
                response=response_status,
            )
        )

        if transaction.response_code == PAYMILL_SUCCESS_CODE:
            self.ticket.pay(
                paid_via='PayMill transaction',
                transaction_id=transaction.id,
            )
            messages.success(
                self.request,
                'Your payment was successfull, you have been emailed a receipt.',
            )
            return self.form_valid()

        else:
            logger.error('transaction failed: {}'.format(response_status, ))
            messages.error(
                self.request,
                'The transaction could not be completed due to the following error:'
                ' {error_message}'.format(
                    error_message=response_status
                ),
            )
            return self.form_invalid()

    def form_invalid(self):
        """
        If the form is invalid, re-render the context data with the
        data-filled form and errors.
        """
        return self.render_to_response(self.get_context_data())

    def form_valid(self):
        """
        If the form is valid, redirect to the supplied URL.
        """
        return HttpResponseRedirect(self.ticket.get_absolute_url())


class TicketReceiptView(TicketDetailView):

    """ Show receipt data for ticket """
    template_name = 'ticket-receipt.html'
